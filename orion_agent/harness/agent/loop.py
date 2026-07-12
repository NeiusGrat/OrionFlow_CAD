"""The agent loop.

Receive a message -> route to a pillar -> assemble context -> call the model
with the pillar's tool subset -> execute tool calls -> feed results back ->
iterate to a final answer or a bounded step cap. Every turn is captured as a
v1.0 trajectory row.

The loop is pillar-agnostic: pillars supply the system prompt, the tool subset
and the verification policy; the loop just runs the conversation and records it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from orion_agent.shared.config import get_config
from orion_agent.shared.contract import ModelTier
from orion_agent.shared.trajectory import (
    Trajectory,
    Message as TrajMessage,
    ToolCall as TrajToolCall,
    Artifact,
    Provenance,
)
from orion_agent.harness.llm.base import LLMClient, LLMMessage
from orion_agent.harness.tools.registry import ToolRegistry
from orion_agent.harness.agent.pillars import GENERATE, Pillar, get_pillar
from orion_agent.harness.agent.repair import RepairPolicy
from orion_agent.harness.agent.router import PillarRouter


@dataclass
class AgentResult:
    final_answer: str
    pillar: str
    model_tier: str
    tool_calls: list[dict] = field(default_factory=list)
    artifacts: list[dict] = field(default_factory=list)
    trajectory: Optional[Trajectory] = None
    thinking: str = ""
    steps: int = 0
    error: str = ""

    def to_response(self) -> dict:
        return {
            "final_answer": self.final_answer,
            "pillar": self.pillar,
            "model_tier": self.model_tier,
            "tool_calls": self.tool_calls,
            "artifacts": self.artifacts,
            "steps": self.steps,
            "error": self.error,
        }


class AgentLoop:
    def __init__(
        self,
        llm: LLMClient,
        registry: ToolRegistry,
        bridge=None,
        config=None,
        router: Optional[PillarRouter] = None,
        verifier=None,
        context_packer=None,
        spec_parser=None,
    ):
        self.llm = llm
        self.registry = registry
        self.bridge = bridge
        self.cfg = config or get_config()
        self.router = router or PillarRouter()
        self.verifier = verifier
        self.context_packer = context_packer
        self.spec_parser = spec_parser

    # ------------------------------------------------------------------ #
    def run(
        self,
        message: str,
        session_id: str = "",
        document: str = "",
        images: Optional[list[str]] = None,
        forced_pillar: Optional[str] = None,
        on_event: Optional[Callable[[dict], None]] = None,
    ) -> AgentResult:
        started = time.time()
        tier = self._detect_tier()
        decision = (
            type("D", (), {"pillar": forced_pillar, "rationale": "forced"})()
            if forced_pillar
            else self.router.route(message, tier=tier, has_image=bool(images))
        )
        pillar = get_pillar(decision.pillar)

        traj = Trajectory(
            session_id=session_id,
            pillar=pillar.name,
            model_tier=tier,
            user_request=message,
            document_name=document,
            provenance=Provenance(
                model=self.cfg.llm.model,
                provider=self.cfg.llm.provider,
                harness_version="0.1.0",
                contract_version="1.0",
            ),
        )

        # Generate runs the Engineering Intent Parser first: the request
        # becomes a structured spec (stated values + unresolved gaps) that
        # conditions generation and gives verification concrete targets.
        spec = None
        if pillar.name == GENERATE and self.spec_parser is not None:
            self._emit(on_event, {"type": "stage", "name": "parse_spec"})
            try:
                parsed = self.spec_parser.parse(message)
            except Exception:  # noqa: BLE001
                parsed = None
            if parsed is not None and not parsed.is_empty():
                spec = parsed
                traj.spec = spec.to_dict()
                self._emit(on_event, {"type": "spec", "spec": traj.spec})

        messages = self._assemble(pillar, message, tier, images, document, spec=spec)
        for m in messages:
            traj.add_message(TrajMessage(role=m.role, content=m.content))

        # Capture a pre-edit baseline so the verifier can prove "nothing else
        # moved" for mutation pillars.
        baseline = None
        edited_names: set[str] = set()
        txn_open = False
        if pillar.allow_mutation and self.verifier is not None:
            try:
                baseline = self.verifier.snapshot()
            except Exception:  # noqa: BLE001
                baseline = None

        tool_schemas = self.registry.schemas(allow=pillar.tools)
        repair = RepairPolicy(budget=getattr(self.cfg.harness, "repair_budget", 3))
        collected_tool_calls: list[dict] = []
        collected_artifacts: list[dict] = []
        last_build_topology: dict = {}
        final_answer = ""
        last_thinking = ""
        step = 0

        for step in range(1, self.cfg.harness.max_agent_steps + 1):
            self._emit(on_event, {"type": "thinking", "step": step})
            response = self.llm.chat(messages, tools=tool_schemas)
            last_thinking = response.thinking or last_thinking

            if response.finish_reason == "error":
                final_answer = response.content
                traj.error = response.content
                break

            # Record assistant turn.
            traj.add_message(TrajMessage(
                role="assistant", content=response.content, thinking=response.thinking,
                tool_calls=[TrajToolCall(name=tc.name, arguments=tc.arguments)
                            for tc in response.tool_calls],
            ))

            if not response.tool_calls:
                final_answer = response.content
                break

            # Execute each tool call and feed results back.
            messages.append(LLMMessage.assistant(response.content, tool_calls=response.tool_calls))
            for tc in response.tool_calls:
                if tc.name not in pillar.tools:
                    obs = f"tool '{tc.name}' is not available in the {pillar.name} route"
                    self._append_tool(messages, traj, tc, obs, ok=False)
                    collected_tool_calls.append({"name": tc.name, "ok": False, "result_preview": obs})
                    continue
                self._emit(on_event, {"type": "tool_call", "name": tc.name, "args": tc.arguments})
                # Wrap the turn's first document mutation in a real FreeCAD
                # transaction so a failed verification can actually roll back.
                tool = self.registry.get(tc.name)
                if (tool is not None and tool.doc_mutating and not txn_open
                        and pillar.allow_mutation and self.bridge is not None):
                    txn_open = self._begin_txn(message)
                result = self.registry.execute(tc.name, tc.arguments)
                # Track which objects an edit touched for unintended-change diff.
                if tc.name in ("set_parameter", "edit_feature") and tc.arguments.get("name"):
                    edited_names.add(tc.arguments["name"])
                if tc.name == "import_shape":
                    if tc.arguments.get("replace"):
                        edited_names.add(tc.arguments["replace"])
                    created = (result.raw or {}).get("created") if isinstance(result.raw, dict) else None
                    if created:
                        edited_names.add(created)
                if tc.name in ("create_featuregraph", "compile_assembly_graph") \
                        and isinstance(result.raw, dict):
                    edited_names.update(result.raw.get("created") or [])
                if tc.name == "write_code" and isinstance(result.raw, dict):
                    last_build_topology = result.raw.get("topology", {}) or last_build_topology
                # Repair policy: classify build failures and append the
                # strategy for the next attempt to what the model observes.
                observation = result.content
                if not result.ok:
                    hint = repair.observe_failure(tc.name, result.content,
                                                  error=result.error or "")
                    if hint:
                        observation = result.content + "\n\n" + hint
                        self._emit(on_event, {"type": "repair",
                                              **repair.attempts[-1]})
                else:
                    repair.observe_success(tc.name)
                preview = result.content[:240]
                self._append_tool(messages, traj, tc, observation, ok=result.ok,
                                  duration_ms=result.duration_ms)
                collected_tool_calls.append({
                    "name": tc.name, "ok": result.ok, "result_preview": preview,
                })
                for art in result.artifacts:
                    collected_artifacts.append(art)
                    traj.add_artifact(Artifact(kind=art.get("kind", "file"),
                                               path=art.get("path", ""),
                                               label=art.get("label", "")))
                self._emit(on_event, {"type": "tool_result", "name": tc.name,
                                      "ok": result.ok, "preview": preview})
        else:
            final_answer = final_answer or (
                "I reached the step limit before finishing. Here is what I "
                "established so far:\n" + (last_thinking[:400] if last_thinking else "")
            )

        # Generate: the deliverable is a model in the user's document, not just
        # a sandbox artifact. If code built but was never imported, import the
        # last STEP now (inside the transaction, so it is verified like any
        # model-initiated edit) and record the outcome honestly.
        if pillar.verification == "artifact":
            wrote_ok = any(c["name"] == "write_code" and c["ok"] for c in collected_tool_calls)
            built_native = any(
                c["name"] in ("create_featuregraph", "compile_assembly_graph") and c["ok"]
                for c in collected_tool_calls
            )
            imported = any(c["name"] == "import_shape" and c["ok"] for c in collected_tool_calls)
            if wrote_ok and not (imported or built_native) and self.bridge is not None:
                if not txn_open:
                    txn_open = self._begin_txn(message)
                auto = self.registry.execute("import_shape", {})
                if auto.ok:
                    imported = True
                    created = (auto.raw or {}).get("created") if isinstance(auto.raw, dict) else None
                    if created:
                        edited_names.add(created)
                    traj.validation.checks["auto_imported"] = True
                    # Harness action, deliberately not added to traj.messages:
                    # the flywheel must not teach the model to skip the import.
                    collected_tool_calls.append({
                        "name": "import_shape", "ok": True,
                        "result_preview": auto.content[:240],
                    })
            delivered = imported or built_native
            traj.validation.executed = wrote_ok or built_native
            traj.validation.checks["imported"] = delivered
            traj.validation.checks["native_build"] = built_native
            if (wrote_ok or built_native) and not delivered:
                final_answer = (final_answer or "") + (
                    "\n\n[Note] The part was built in the sandbox but could not "
                    "be imported into the FreeCAD document."
                )

        # Pillar verification: run the four-check loop for mutation pillars.
        if self.verifier is not None and pillar.allow_mutation and edited_names:
            try:
                self.verifier.verify(
                    pillar, traj, collected_artifacts,
                    before=baseline, edited_names=edited_names,
                    spec=traj.spec or None,
                )
            except Exception as exc:  # noqa: BLE001
                traj.validation.notes = f"verifier error: {exc}"

        # Resolve the pending transaction from the verification verdict: hard
        # failures (broken recompute, dead downstream feature, geometry moved
        # outside the edit) roll back; everything else commits. Intent-check
        # misses alone don't revert — that check is heuristic.
        rolled_back = False
        if txn_open and self.bridge is not None:
            try:
                if self._hard_failed(traj.validation):
                    self.bridge.abort_transaction()
                    rolled_back = True
                else:
                    self.bridge.commit_transaction()
            except Exception as exc:  # noqa: BLE001
                traj.validation.notes = (
                    (traj.validation.notes + "; ") if traj.validation.notes else ""
                ) + f"transaction error: {exc}"
        traj.validation.checks["rolled_back"] = rolled_back

        if pillar.allow_mutation and edited_names and not traj.validation.passed():
            final_answer = self._append_verification_note(
                final_answer, traj.validation, rolled_back
            )

        if pillar.verification == "grounding":
            traj.validation.grounded = bool(
                any(c["ok"] for c in collected_tool_calls)
            ) or not self._is_quantitative(message)

        if pillar.verification == "render_compare" and last_build_topology:
            from orion_agent.harness.agent.reconstruct import parse_target, score_reconstruction
            score = score_reconstruction(last_build_topology, parse_target(message))
            traj.validation.divergence = score.divergence
            traj.validation.checks["reconstruction"] = {
                "confidence": score.confidence, "detail": score.detail,
            }
            if not score.dimensional_match:
                final_answer = (final_answer or "") + (
                    f"\n\n[Reconstruct] Confidence {score.confidence:.0%} — the "
                    f"rebuilt model diverges from the drawing ({score.detail}). "
                    "Treat this reconstruction as approximate."
                )

        # Repair record: attempts, budget, and whether the turn recovered —
        # this is what "repair recovery rate" is computed from in evals.
        repair_summary = repair.summary()
        if repair_summary is not None:
            traj.validation.checks["repair"] = repair_summary

        traj.final_answer = final_answer
        traj.step_count = step
        traj.duration_ms = (time.time() - started) * 1000

        return AgentResult(
            final_answer=final_answer,
            pillar=pillar.name,
            model_tier=tier,
            tool_calls=collected_tool_calls,
            artifacts=collected_artifacts,
            trajectory=traj,
            thinking=last_thinking,
            steps=step,
            error=traj.error,
        )

    # ------------------------------------------------------------------ #
    def _assemble(self, pillar: Pillar, message: str, tier: str,
                  images: Optional[list[str]], document: str = "",
                  spec=None) -> list[LLMMessage]:
        if self.context_packer is not None:
            return self.context_packer.pack(pillar, message, tier, images,
                                            self.bridge, document=document,
                                            spec=spec)
        system = pillar.system_prompt
        if tier and tier != ModelTier.UNKNOWN:
            system += f"\n\nThe open model is classified as Tier {tier}."
        if spec is not None:
            rendered = spec.render()
            if rendered:
                system += ("\n\n--- Engineering specification (parsed from the "
                           "request) ---\n" + rendered)
        return [LLMMessage.system(system), LLMMessage.user(message, images=images)]

    def _begin_txn(self, message: str) -> bool:
        try:
            self.bridge.begin_transaction(f"OrionFlow: {message[:48]}")
            return True
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _hard_failed(vb) -> bool:
        return any(f is False for f in (vb.executed, vb.edit_survived,
                                        vb.no_unintended_change))

    def _detect_tier(self) -> str:
        if self.bridge is None:
            return ModelTier.UNKNOWN
        try:
            return self.bridge.get_model_tier().get("tier", ModelTier.UNKNOWN)
        except Exception:  # noqa: BLE001
            return ModelTier.UNKNOWN

    @staticmethod
    def _append_tool(messages, traj, tc, content, ok=True, duration_ms=0.0):
        messages.append(LLMMessage.tool(content, tool_call_id=tc.id, name=tc.name))
        traj.add_message(TrajMessage(role="tool", content=content[:1000],
                                     tool_call_id=tc.id, name=tc.name))
        if traj.messages:
            for m in reversed(traj.messages):
                if m.role == "assistant" and m.tool_calls:
                    for call in m.tool_calls:
                        if call.name == tc.name and not call.result_preview:
                            call.result_preview = content[:240]
                            call.ok = ok
                            call.duration_ms = duration_ms
                            break
                    break

    @staticmethod
    def _append_verification_note(answer: str, vb, rolled_back: bool = False) -> str:
        failed = []
        if vb.executed is False:
            failed.append("the model did not recompute cleanly")
        if vb.edit_survived is False:
            failed.append("a downstream feature broke")
        if vb.no_unintended_change is False:
            failed.append("geometry outside the edited region changed")
        if vb.intent_consistent is False:
            failed.append("the result does not appear to match the stated intent")
        if not failed:
            return answer
        tail = ("The change was rolled back." if rolled_back
                else "The change is still in the document — use undo to revert it.")
        note = ("\n\n[Verification] I could not confirm this edit is safe: "
                + "; ".join(failed) + ". " + tail)
        return (answer or "") + note

    @staticmethod
    def _is_quantitative(message: str) -> bool:
        cues = ("how many", "how far", "distance", "dimension", "volume", "count",
                "measure", "thick", "wide", "long", "diameter", "radius")
        return any(c in message.lower() for c in cues)

    @staticmethod
    def _emit(cb, event):
        if cb is not None:
            try:
                cb(event)
            except Exception:  # noqa: BLE001
                pass

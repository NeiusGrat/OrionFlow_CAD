"""Context budget packer.

Deterministic assembly of the prompt the model sees: system prompt + a
token-bounded snapshot of the open model + relevant memory + the user message.
Heavy topology is summarised, not pasted whole; the model can expand on demand
via the ``expand_topology`` tool.

This keeps large models (hundreds of features) inside the token budget without
the agent loop having to think about it.
"""

from __future__ import annotations

from typing import Optional

from orion_agent.shared.contract import ModelTier
from orion_agent.harness.llm.base import LLMMessage
from orion_agent.harness.topology import summarize_topology, estimate_tokens


class ContextPacker:
    def __init__(self, memory=None, state_token_budget: int = 1200):
        self.memory = memory
        self.state_token_budget = state_token_budget

    def pack(self, pillar, message: str, tier: str,
             images: Optional[list[str]], bridge, document: str = "",
             spec=None) -> list[LLMMessage]:
        system = pillar.system_prompt
        if tier and tier != ModelTier.UNKNOWN:
            system += f"\n\nThe open model is classified as Tier {tier}."

        state = self._model_state(bridge)
        if state:
            system += "\n\n--- Current model snapshot ---\n" + state

        if self.memory is not None:
            doc_key = document or self._document_name(bridge)
            mem = self.memory.get(doc_key) if doc_key else None
            mem_summary = mem.summary() if mem else ""
            if mem_summary:
                system += "\n\n--- Memory (this document) ---\n" + mem_summary

        # Generation turns get worked FeatureGraph examples matched to the
        # request, so graph structure is never produced zero-shot.
        if pillar.name in ("generate", "reconstruct"):
            from orion_agent.harness.exemplars import render_examples
            system += ("\n\n--- Worked examples (imitate this structure) ---\n"
                       + render_examples(message))

        # The parsed engineering spec goes last so the stated values and the
        # unresolved gaps sit closest to the user message.
        if spec is not None:
            rendered = spec.render()
            if rendered:
                system += ("\n\n--- Engineering specification (parsed from the "
                           "request) ---\n" + rendered)

        return [LLMMessage.system(system), LLMMessage.user(message, images=images)]

    # ------------------------------------------------------------------ #
    def _model_state(self, bridge) -> str:
        if bridge is None:
            return ""
        try:
            objs = bridge.list_objects().get("objects", [])
        except Exception:  # noqa: BLE001
            return ""
        if not objs:
            return "(no objects in document)"
        lines = []
        for o in objs[:30]:
            kind = "parametric" if o.get("parametric") else "imported"
            lines.append(f"- {o['name']} [{o.get('type_id', '?')}] {kind}")
        text = "\n".join(lines)
        if len(objs) > 30:
            text += f"\n... and {len(objs) - 30} more"

        # Append a compact topology summary if it fits the budget.
        try:
            topo = summarize_topology(bridge.inspect_topology(None))
            if estimate_tokens(text + topo) <= self.state_token_budget:
                text += "\n\nTopology:\n" + topo
        except Exception:  # noqa: BLE001
            pass
        return text

    @staticmethod
    def _document_name(bridge) -> str:
        if bridge is None:
            return ""
        try:
            return bridge.get_document_state().get("name", "") or ""
        except Exception:  # noqa: BLE001
            return ""

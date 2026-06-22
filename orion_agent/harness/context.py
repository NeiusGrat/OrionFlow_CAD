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
             images: Optional[list[str]], bridge) -> list[LLMMessage]:
        system = pillar.system_prompt
        if tier and tier != ModelTier.UNKNOWN:
            system += f"\n\nThe open model is classified as Tier {tier}."

        state = self._model_state(bridge)
        if state:
            system += "\n\n--- Current model snapshot ---\n" + state

        if self.memory is not None:
            mem = self.memory.get(self._doc_hint(message))
            mem_summary = mem.summary() if mem else ""
            if mem_summary:
                system += "\n\n--- Memory (this document) ---\n" + mem_summary

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
    def _doc_hint(_message: str) -> str:
        # Document scoping is provided by the loop via memory.observe; the packer
        # only needs a best-effort key here.
        return ""

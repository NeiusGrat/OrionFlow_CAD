"""What a skill is, and what it must hand back.

A skill resolves an engineering request into the variables of a known part
family, plus the reasoning that justifies each number. The split matters: the
variables are what gets built and verified, and the citations are what makes the
result defensible to an engineer. Neither is allowed to leak into the other —
the design prompt sees dimensions, the user sees why.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


class SkillError(ValueError):
    """The request cannot be satisfied, with the reason stated.

    Raised rather than returned when the skill would otherwise have to invent
    something — an unknown bearing, a fit class with no sourced deviations, a
    seat that cannot physically fit the housing. Failing loudly is the whole
    point: the alternative is a plausible part that is wrong.
    """


@dataclass
class SkillResult:
    """A resolved sub-design."""

    #: The part family these variables belong to.
    part_class: str
    #: Variables in that family's own vocabulary — directly buildable.
    variables: dict[str, float] = field(default_factory=dict)
    #: variable -> why it has this value, in one line an engineer can check.
    rationale: dict[str, str] = field(default_factory=dict)
    #: Standards, catalogue entries and manufacturer recommendations relied on.
    citations: list[str] = field(default_factory=list)
    #: Derived quantities worth showing but not part of the geometry: fit
    #: limits, clearances, engagement lengths.
    derived: dict[str, Any] = field(default_factory=dict)
    #: Things the caller should know: a value outside the verified range, an
    #: assumption made, a check that could not be performed.
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        """A block for a model or a user. Numbers first, reasons attached."""
        lines = [f"{self.part_class}:"]
        lines += [f"  {k} = {v:g}   {self.rationale.get(k, '')}".rstrip()
                  for k, v in sorted(self.variables.items())]
        if self.derived:
            lines.append("derived:")
            lines += [f"  {k}: {v}" for k, v in self.derived.items()]
        if self.citations:
            lines.append("per: " + "; ".join(self.citations))
        for w in self.warnings:
            lines.append(f"NOTE: {w}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {"part_class": self.part_class, "variables": self.variables,
                "rationale": self.rationale, "citations": self.citations,
                "derived": self.derived, "warnings": self.warnings}


@dataclass
class Skill:
    """One engineering capability, exposed as a single tool."""

    name: str
    description: str
    parameters: dict[str, Any]          # JSON schema
    run: Callable[..., SkillResult]

    def schema(self) -> dict:
        return {"type": "function",
                "function": {"name": self.name,
                             "description": self.description,
                             "parameters": self.parameters}}


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> Skill:
        self._skills[skill.name] = skill
        return skill

    def get(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)

    def names(self) -> list[str]:
        return sorted(self._skills)

    def schemas(self) -> list[dict]:
        return [self._skills[n].schema() for n in self.names()]

    def execute(self, name: str, arguments: dict) -> SkillResult:
        skill = self._skills.get(name)
        if skill is None:
            raise SkillError(f"unknown skill {name!r}; known: "
                             f"{', '.join(self.names())}")
        return skill.run(**(arguments or {}))


registry = SkillRegistry()


def _load_skills() -> None:
    """Import the modules that register skills. Kept here so ``registry`` is
    populated by importing the package, not by remembering to import each one."""
    from orion.skills import bearing_seat, bolt_pattern  # noqa: F401


_load_skills()

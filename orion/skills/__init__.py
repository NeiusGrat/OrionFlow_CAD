"""Engineering skills: the model reasons about parts, not about builders.

Every studio failure of the "invented vocabulary" kind looks the same —
``unknown profile builder 'rect_wit…'``, a parameter that does not exist, a
sketch argument spelled wrong. The model is being asked to speak a low-level CAD
dialect it half-remembers, and there is no amount of prompting that makes a
half-remembered vocabulary reliable.

A skill removes the vocabulary from the model's job. ``create_bearing_seat``
takes a bearing designation and a duty; underneath it looks up the boundary
dimensions, selects the ISO fit, computes the housing bore limits from the IT
grade, derives the shoulder diameter from the manufacturer's abutment
recommendation, checks the result against the family's own guards, and returns a
complete, buildable parameter set. The model never names a builder because it
never sees one.

Two rules the skills here follow, both learned from measurement:

* **Never invent a number.** A skill that cannot source a value says so and
  refuses. A fit table that is subtly wrong produces a housing that assembles
  wrongly with nothing to indicate it — the same silent-wrongness class as a
  part that verifies its own mistaken prediction.
* **Return parameters the compiler already accepts.** Skills resolve to the
  variables of a known family, so everything downstream — static check, guards,
  closed-form verification — applies unchanged. A skill cannot smuggle geometry
  past the verifier.
"""

from __future__ import annotations

from orion.skills.base import Skill, SkillError, SkillResult, registry

__all__ = ["Skill", "SkillError", "SkillResult", "registry"]

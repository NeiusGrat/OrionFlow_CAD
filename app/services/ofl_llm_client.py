"""LLM client for generating OFL code from text prompts.

Currently uses Groq API. When fine-tuned model is ready, swap OFL_LLM_PROVIDER.
"""

import logging
from app.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are OrionFlow, a CAD code generator. Given a description of a mechanical part,
output executable Python code using the orionflow_ofl library.

Rules:
- Always start with: from orionflow_ofl import *
- Define all dimensions as named variables at the top
- Use Sketch(Plane.XY).rect(w, h).extrude(t) for rectangular plates
- Use Sketch(Plane.XY).circle(diameter).extrude(t) for circular parts
- Use Sketch(Plane.XY).rounded_rect(w, h, r).extrude(t) for rounded plates
- Use Hole(diameter).at(x, y).through().label("name") for holes
- Use Hole(diameter).at_circular(radius, count, start_angle).through() for bolt patterns
- Use part -= hole for boolean subtraction
- Always end with: export(part, "part.step")
- Output ONLY Python code, no explanations, no markdown fences."""

FEW_SHOT = [
    {
        "user": "Flat washer, 24mm outer diameter, 13mm center hole, 2.5mm thick",
        "assistant": (
            'from orionflow_ofl import *\n\n'
            'od = 24\nhole_dia = 13\nthickness = 2.5\n\n'
            'part = Sketch(Plane.XY).circle(od).extrude(thickness)\n'
            'part -= Hole(hole_dia).at(0, 0).through().label("center_bore")\n\n'
            'export(part, "part.step")'
        ),
    },
    {
        "user": "NEMA-17 motor mount. 60mm square, 6mm thick, 3mm corner radius. Center bore 22mm. Four M5 holes on 31mm PCD at 45 degrees.",
        "assistant": (
            'from orionflow_ofl import *\n\n'
            'plate_size = 60\nthickness = 6\ncorner_r = 3\nbore_dia = 22\nbolt_dia = 5.5\nbolt_pcd = 31\n\n'
            'part = Sketch(Plane.XY).rounded_rect(plate_size, plate_size, corner_r).extrude(thickness)\n\n'
            'part -= Hole(bore_dia).at(0, 0).through().label("shaft_bore")\n'
            'part -= Hole(bolt_dia).at_circular(bolt_pcd / 2, count=4, start_angle=45).through().label("M5_mount")\n\n'
            'export(part, "part.step")'
        ),
    },
    {
        "user": "Circular flange. 100mm diameter, 8mm thick. 50mm center bore. Six M8 bolt holes on 75mm PCD.",
        "assistant": (
            'from orionflow_ofl import *\n\n'
            'plate_dia = 100\nthickness = 8\nbore_dia = 50\nbolt_dia = 8.4\nbolt_pcd = 75\nbolt_count = 6\n\n'
            'part = Sketch(Plane.XY).circle(plate_dia).extrude(thickness)\n\n'
            'part -= Hole(bore_dia).at(0, 0).through().label("center_bore")\n'
            'part -= Hole(bolt_dia).at_circular(bolt_pcd / 2, count=bolt_count, start_angle=0).through().label("M8_mount")\n\n'
            'export(part, "part.step")'
        ),
    },
]


class OFLLLMClient:
    """Generates OFL code from text. Pluggable backend (groq / local)."""

    def __init__(self, provider: str = None):
        self.provider = provider or getattr(settings, "ofl_llm_provider", "groq")

        if self.provider == "groq":
            self._init_groq()
        elif self.provider == "local":
            raise NotImplementedError("Local model not yet available. Use provider='groq'.")
        else:
            raise ValueError(f"Unknown OFL LLM provider: {self.provider}")

    def _init_groq(self):
        try:
            from groq import Groq
        except ImportError:
            raise ImportError("pip install groq")

        api_key = settings.groq_api_key
        if not api_key:
            raise ValueError("GROQ_API_KEY not set in .env")

        self.client = Groq(api_key=api_key)
        self.model = getattr(settings, "ofl_groq_model", "llama-3.3-70b-versatile")

    def generate(self, prompt: str) -> str:
        """Generate OFL code from natural language. Returns code string."""
        if self.provider == "groq":
            return self._generate_groq(prompt)
        raise NotImplementedError

    def _generate_groq(self, prompt: str) -> str:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for ex in FEW_SHOT:
            messages.append({"role": "user", "content": ex["user"]})
            messages.append({"role": "assistant", "content": ex["assistant"]})
        messages.append({"role": "user", "content": prompt})

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.1,
            max_tokens=1024,
        )
        raw = response.choices[0].message.content
        return self._clean_code(raw)

    def generate_edit(self, current_code: str, edit_instruction: str) -> str:
        """Apply a natural language edit to existing OFL code."""
        edit_prompt = (
            f"Here is existing OFL code:\n\n```python\n{current_code}\n```\n\n"
            f"Apply this edit: {edit_instruction}\n\n"
            "Output the COMPLETE modified OFL code. Change only what's needed.\n"
            "Output ONLY the code, no explanations."
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": edit_prompt},
        ]
        response = self.client.chat.completions.create(
            model=self.model, messages=messages,
            temperature=0.1, max_tokens=1024,
        )
        return self._clean_code(response.choices[0].message.content)

    @staticmethod
    def _clean_code(raw: str) -> str:
        """Strip markdown fences from LLM output."""
        text = raw.strip()
        if "```python" in text:
            start = text.index("```python") + len("```python")
            end = text.index("```", start) if "```" in text[start:] else len(text)
            text = text[start:end].strip()
        elif "```" in text:
            start = text.index("```") + 3
            end = text.index("```", start) if "```" in text[start:] else len(text)
            text = text[start:end].strip()
        return text

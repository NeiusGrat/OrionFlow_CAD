"""LLM client for generating OFL code from text prompts.

Supports Groq for hosted inference and Ollama for local open-source models.
"""

import logging

import requests

from app.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are OrionFlow, a CAD code generator. Given a description of a mechanical part,
output executable Python code using the orionflow_ofl library.

COORDINATE SYSTEM (critical):
- Every profile (rect, rounded_rect, circle) is CENTERED on the origin (0, 0).
- polygon() is the exception: its vertices are used exactly as given, NOT recentered.
- Hole positions in .at(x, y) are measured FROM THE PART CENTER, not from a corner.
- A hole inset i from the corner of a w x h plate is at (+-(w/2 - i), +-(h/2 - i)).
- Extrusion goes from Z=0 up to Z=thickness.

DIMENSION RULES (critical):
- Stated dimensions are the OUTER envelope of the FINISHED part. Walls, ribs and
  flanges fit INSIDE them — never grow the part beyond the stated size.
- "Hollow box with w mm walls" = solid outer box, then .shell(w, open_face=None).
  "Open-top box / tray" = .shell(w, open_face="top"). Never build walls piece by piece.
- "t mm thick" is the plate/wall thickness (the small dimension), never the part height.
- Exception: explicitly requested mounting EARS, lugs or tabs attach OUTSIDE the stated
  body footprint (that is their purpose) — fuse them to the body, then drill their holes
  at the ear centers.

API:
- Always start with: from orionflow_ofl import *
- Define all dimensions as named variables at the top
- Sketch(Plane.XY).rect(w, h).extrude(t) for rectangular plates
- Sketch(Plane.XY).rounded_rect(w, h, r).extrude(t) for rounded-corner plates
- Sketch(Plane.XY).circle(diameter).extrude(t) for circular parts
- Sketch(Plane.XY).polygon([(x1, y1), (x2, y2), ...]).extrude(t) for triangles, gussets, hexagons
- Sketch(Plane.XY, offset=z).circle(d).extrude(t) to start a feature at height z (e.g. a boss on top of a base)
- part.rotate(angle_deg, axis="x") rotates about that global axis through the origin; axis: "x" | "y" | "z"
- part.translate(x, y, z) moves the part; position pieces BEFORE fusing them
- part += other_part to fuse two parts (boss on a plate, stacked steps, bracket legs)
- Sketch(Plane.XY).slot(length, width).extrude(t) for a stadium/obround slot (length tip-to-tip, long axis along X; .rotate(90) for a Y slot)
- Hole(diameter).at(x, y).through().label("name") for a through hole
- Hole(diameter).at(x, y).to_depth(d) for a blind hole (from the top face down)
- Hole(diameter).at_circular(radius, count, start_angle).through() for a circular bolt pattern (radius = PCD/2)
- Hole(diameter).along("x").at(y, z).through() for a SIDE hole drilled along X; .along("y").at(x, z) drills along Y. Use this for holes in upright walls — do NOT rotate the part to drill it
- .at() takes exactly TWO coordinates. Blind holes default to entering from the TOP face; Hole(d).at(x, y).to_depth(depth, from_face="bottom") enters from the bottom/min face
- Hollow tube with bearing bores in both end walls: shell(wall, open_face=None) for a closed shell, then ONE Hole(...).through() cuts both end walls in a single operation
- .translate()/.rotate() MUTATE the part and return it. In a loop, CREATE the piece inside the loop body — never reuse one piece with cumulative translates (use .copy() to clone)
- Every piece you += must touch or overlap the main body — disconnected pieces are an error
- part -= hole for boolean subtraction
- part -= cutter_part subtracts another Part: use for slots, rectangular cutouts and pockets (build the cutter slightly taller than the plate and .translate(z=-1) so it cuts clean through)
- part.fillet(r, edges="vertical") rounds edges; edges: "all" | "top" | "bottom" | "vertical"
- part.chamfer(d, edges="top") chamfers edges; same edge selectors
- part.shell(wall, open_face="top") hollows the part leaving a wall; open_face: "top" | "bottom" | None
- Always end with: export(part, "part.step")
- Output ONLY Python code, no explanations, no markdown fences."""

FEW_SHOT = [
    {
        "user": "Flat washer, 24mm outer diameter, 13mm center hole, 2.5mm thick",
        "assistant": (
            "from orionflow_ofl import *\n\n"
            "od = 24\nhole_dia = 13\nthickness = 2.5\n\n"
            "part = Sketch(Plane.XY).circle(od).extrude(thickness)\n"
            'part -= Hole(hole_dia).at(0, 0).through().label("center_bore")\n\n'
            'export(part, "part.step")'
        ),
    },
    {
        "user": "NEMA-17 motor mount. 60mm square, 6mm thick, 3mm corner radius. Center bore 22mm. Four M5 holes on 31mm PCD at 45 degrees.",
        "assistant": (
            "from orionflow_ofl import *\n\n"
            "plate_size = 60\nthickness = 6\ncorner_r = 3\nbore_dia = 22\nbolt_dia = 5.5\nbolt_pcd = 31\n\n"
            "part = Sketch(Plane.XY).rounded_rect(plate_size, plate_size, corner_r).extrude(thickness)\n\n"
            'part -= Hole(bore_dia).at(0, 0).through().label("shaft_bore")\n'
            'part -= Hole(bolt_dia).at_circular(bolt_pcd / 2, count=4, start_angle=45).through().label("M5_mount")\n\n'
            'export(part, "part.step")'
        ),
    },
    {
        "user": "Circular flange. 100mm diameter, 8mm thick. 50mm center bore. Six M8 bolt holes on 75mm PCD.",
        "assistant": (
            "from orionflow_ofl import *\n\n"
            "plate_dia = 100\nthickness = 8\nbore_dia = 50\nbolt_dia = 8.4\nbolt_pcd = 75\nbolt_count = 6\n\n"
            "part = Sketch(Plane.XY).circle(plate_dia).extrude(thickness)\n\n"
            'part -= Hole(bore_dia).at(0, 0).through().label("center_bore")\n'
            'part -= Hole(bolt_dia).at_circular(bolt_pcd / 2, count=bolt_count, start_angle=0).through().label("M8_mount")\n\n'
            'export(part, "part.step")'
        ),
    },
    {
        "user": "Mounting plate 120x80mm, 6mm thick, four M5 holes inset 10mm from each corner.",
        "assistant": (
            "from orionflow_ofl import *\n\n"
            "plate_w = 120\nplate_h = 80\nthickness = 6\nbolt_dia = 5.5\ninset = 10\n\n"
            "hole_x = plate_w / 2 - inset\nhole_y = plate_h / 2 - inset\n\n"
            "part = Sketch(Plane.XY).rect(plate_w, plate_h).extrude(thickness)\n\n"
            "part -= (\n"
            "    Hole(bolt_dia)\n"
            "    .at(-hole_x, -hole_y)\n"
            "    .at(hole_x, -hole_y)\n"
            "    .at(-hole_x, hole_y)\n"
            "    .at(hole_x, hole_y)\n"
            '    .through()\n    .label("M5_corner")\n'
            ")\n\n"
            'export(part, "part.step")'
        ),
    },
    {
        "user": "Bearing housing: 62mm diameter base 8mm thick, 45mm diameter boss 15mm tall on top, 25mm bore through everything, four M5 holes on 52mm PCD. Chamfer the top edge of the boss 1mm.",
        "assistant": (
            "from orionflow_ofl import *\n\n"
            "base_dia = 62\nbase_h = 8\nboss_dia = 45\nboss_h = 15\nbore_dia = 25\nbolt_dia = 5.5\nbolt_pcd = 52\nchamfer_d = 1\n\n"
            "part = Sketch(Plane.XY).circle(base_dia).extrude(base_h)\n"
            "boss = Sketch(Plane.XY, offset=base_h).circle(boss_dia).extrude(boss_h)\n"
            "part += boss\n"
            'part.chamfer(chamfer_d, edges="top")\n\n'
            'part -= Hole(bore_dia).at(0, 0).through().label("bearing_bore")\n'
            'part -= Hole(bolt_dia).at_circular(bolt_pcd / 2, count=4, start_angle=45).through().label("M5_mount")\n\n'
            'export(part, "part.step")'
        ),
    },
    {
        "user": "Triangular gusset plate, 40mm legs, 5mm thick.",
        "assistant": (
            "from orionflow_ofl import *\n\n"
            "leg = 40\nthickness = 5\n\n"
            "part = Sketch(Plane.XY).polygon([(0, 0), (leg, 0), (0, leg)]).extrude(thickness)\n\n"
            'export(part, "part.step")'
        ),
    },
    {
        "user": "Plate 80x40mm, 5mm thick, with a central slot 40mm long and 8mm wide.",
        "assistant": (
            "from orionflow_ofl import *\n\n"
            "plate_w = 80\nplate_h = 40\nthickness = 5\nslot_len = 40\nslot_w = 8\n\n"
            "part = Sketch(Plane.XY).rect(plate_w, plate_h).extrude(thickness)\n\n"
            "# cutter taller than the plate, dropped 1mm so it cuts clean through\n"
            "slot = Sketch(Plane.XY).slot(slot_len, slot_w).extrude(thickness + 2).translate(z=-1)\n"
            "part -= slot\n\n"
            'export(part, "part.step")'
        ),
    },
    {
        "user": "Closed hollow box 50 x 50 x 50 mm with 4 mm walls.",
        "assistant": (
            "from orionflow_ofl import *\n\n"
            "size = 50\nwall = 4\n\n"
            "# the stated 50 mm is the OUTER size: build the solid envelope first,\n"
            "# then hollow it. The part itself is NEVER the inner cavity.\n"
            "part = Sketch(Plane.XY).rect(size, size).extrude(size)\n"
            "part.shell(wall, open_face=None)  # closed on all six faces\n\n"
            'export(part, "part.step")'
        ),
    },
    {
        "user": "T-shaped flat bracket 70 mm wide, 50 mm tall, 6 mm thick, arms 20 mm wide.",
        "assistant": (
            "from orionflow_ofl import *\n\n"
            "width = 70\nheight = 50\nt = 6\narm_w = 20\n\n"
            "# a FLAT bracket lies in the XY plane and is extruded by its thickness.\n"
            "# T = top bar + stem, fused edge-to-edge inside the stated envelope.\n"
            "top = Sketch(Plane.XY).rect(width, arm_w).extrude(t)\n"
            "top.translate(0, height / 2 - arm_w / 2, 0)\n"
            "stem = Sketch(Plane.XY).rect(arm_w, height - arm_w).extrude(t)\n"
            "stem.translate(0, -arm_w / 2, 0)\n"
            "part = top + stem\n\n"
            'export(part, "part.step")'
        ),
    },
    {
        "user": "Tube 50mm OD, 40mm ID, 70mm long.",
        "assistant": (
            "from orionflow_ofl import *\n\n"
            "od = 50\nbore_dia = 40\nlength = 70\n\n"
            "# circular tube = solid cylinder at the OD, then bore the ID through.\n"
            "# NEVER shell() a round tube — the bore IS the inner diameter.\n"
            "part = Sketch(Plane.XY).circle(od).extrude(length)\n"
            'part -= Hole(bore_dia).at(0, 0).through().label("bore")\n\n'
            'export(part, "part.step")'
        ),
    },
    {
        "user": "Hollow rectangular tube 100mm long, 40x25mm cross-section, 3mm walls, with a 20mm bore through each end wall.",
        "assistant": (
            "from orionflow_ofl import *\n\n"
            "length = 100\nouter_w = 40\nouter_h = 25\nwall = 3\nbore_dia = 20\n\n"
            "# the STATED cross-section is the OUTER envelope — sketch it directly\n"
            "part = Sketch(Plane.XY).rect(outer_w, outer_h).extrude(length)\n"
            "part.shell(wall, open_face=None)  # hollow, both end walls kept\n\n"
            "# one through hole bores BOTH end walls in a single operation\n"
            'part -= Hole(bore_dia).at(0, 0).through().label("end_bores")\n\n'
            'export(part, "part.step")'
        ),
    },
    {
        "user": "Heat sink 40x40mm, 4mm base, with 5 fins 15mm tall and 2mm thick.",
        "assistant": (
            "from orionflow_ofl import *\n\n"
            "base = 40\nbase_t = 4\nfin_count = 5\nfin_h = 15\nfin_t = 2\n\n"
            "part = Sketch(Plane.XY).rect(base, base).extrude(base_t)\n\n"
            "# fins sit ON the base (offset=base_t). Create each fin INSIDE the\n"
            "# loop: transforms mutate, so a reused piece would drift.\n"
            "pitch = (base - fin_t) / (fin_count - 1)\n"
            "for i in range(fin_count):\n"
            "    x = -base / 2 + fin_t / 2 + i * pitch\n"
            "    fin = Sketch(Plane.XY, offset=base_t).rect(fin_t, base).extrude(fin_h)\n"
            "    fin.translate(x, 0, 0)\n"
            "    part += fin\n\n"
            'export(part, "part.step")'
        ),
    },
    {
        "user": "Pulley 50mm OD, 12mm wide, 16mm bore with a 5mm wide, 3mm deep keyway.",
        "assistant": (
            "from orionflow_ofl import *\n\n"
            "od = 50\nwidth = 12\nbore_dia = 16\nkey_w = 5\nkey_d = 3\n\n"
            "part = Sketch(Plane.XY).circle(od).extrude(width)\n"
            'part -= Hole(bore_dia).at(0, 0).through().label("bore")\n\n'
            "# keyway: rectangular cutter reaching key_d beyond the bore wall.\n"
            "# Overlap 2mm INTO the bore so it always removes material.\n"
            "overlap = 2\n"
            "key_cut = Sketch(Plane.XY).rect(key_d + overlap, key_w).extrude(width + 2)\n"
            "key_cut.translate(bore_dia / 2 - overlap + (key_d + overlap) / 2, 0, -1)\n"
            "part -= key_cut\n\n"
            'export(part, "part.step")'
        ),
    },
    {
        "user": "Angle bracket: 60mm base with two 5mm holes, 50mm upright wall with two 5mm holes, 40mm wide, 5mm thick.",
        "assistant": (
            "from orionflow_ofl import *\n\n"
            "base_len = 60\nwall_h = 50\nwidth = 40\nt = 5\nhole_dia = 5\n\n"
            "base = Sketch(Plane.XY).rect(base_len, width).extrude(t)\n\n"
            "wall = Sketch(Plane.XY).rect(wall_h, width).extrude(t)\n"
            'wall.rotate(90, axis="y")  # wall_h now runs along Z, t along X\n'
            "wall.translate(-base_len / 2 + t / 2, 0, wall_h / 2)\n\n"
            "part = base + wall\n\n"
            'part -= Hole(hole_dia).at(base_len / 2 - 15, 0).at(base_len / 2 - 35, 0).through().label("base_holes")\n'
            "# wall holes are drilled ALONG X (through the upright wall): .at(y, z)\n"
            'part -= Hole(hole_dia).along("x").at(0, wall_h - 15).at(0, wall_h - 35).through().label("wall_holes")\n\n'
            'export(part, "part.step")'
        ),
    },
    {
        "user": "L bracket: 50mm base, 40mm upright wall, 30mm wide, 4mm thick, with two 5mm holes in the base.",
        "assistant": (
            "from orionflow_ofl import *\n\n"
            "base_len = 50\nwall_h = 40\nwidth = 30\nt = 4\nhole_dia = 5\n\n"
            "base = Sketch(Plane.XY).rect(base_len, width).extrude(t)\n\n"
            "# upright wall: build flat, stand it up, slide flush with the base end\n"
            "wall = Sketch(Plane.XY).rect(wall_h, width).extrude(t)\n"
            'wall.rotate(90, axis="y")  # wall_h now runs along Z, t along X\n'
            "wall.translate(-base_len / 2, 0, wall_h / 2)\n\n"
            "part = base + wall\n\n"
            'part -= Hole(hole_dia).at(base_len / 2 - 12, 0).at(base_len / 2 - 32, 0).through().label("base_holes")\n\n'
            'export(part, "part.step")'
        ),
    },
]


class OFLLLMClient:
    """Generates OFL code from text. Pluggable backend (groq / ollama / local)."""

    def __init__(self, provider: str = None):
        self.provider = (
            provider or getattr(settings, "ofl_llm_provider", "groq")
        ).lower()

        if self.provider == "groq":
            self._init_groq()
        elif self.provider == "k2think":
            self._init_k2think()
        elif self.provider == "ollama":
            self._init_ollama()
        elif self.provider == "local":
            raise NotImplementedError(
                "Local model path inference not yet available. Use provider='ollama'."
            )
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

    def _init_ollama(self):
        self.base_url = getattr(
            settings, "ollama_base_url", "http://localhost:11434"
        ).rstrip("/")
        self.model = getattr(settings, "ofl_ollama_model", "qwen2.5-coder:7b")
        self.timeout = getattr(settings, "ofl_ollama_timeout_seconds", 600)

    def _init_k2think(self):
        api_key = settings.k2think_api_key
        if not api_key:
            raise ValueError("K2THINK_API_KEY not set")
        self.api_key = api_key
        self.base_url = settings.k2think_base_url
        self.model = settings.k2think_model
        self.timeout = settings.ofl_k2think_timeout_seconds

    def generate(self, prompt: str) -> str:
        """Generate OFL code from natural language. Returns code string."""
        return self._clean_code(self._chat(self._build_messages(prompt)))

    def repair(self, code: str, error: str, original_prompt: str) -> str:
        """Ask the LLM to fix OFL code that failed to execute."""
        repair_prompt = (
            f'The user asked for: "{original_prompt}"\n\n'
            f"This OFL code was generated:\n```python\n{code}\n```\n\n"
            f"Executing it failed with this error:\n{error}\n\n"
            "Output the COMPLETE corrected OFL code. Fix only what is needed.\n"
            "Output ONLY the code, no explanations."
        )
        return self._clean_code(self._chat(self._build_messages(repair_prompt)))

    def _build_messages(self, prompt: str) -> list[dict[str, str]]:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for ex in FEW_SHOT:
            messages.append({"role": "user", "content": ex["user"]})
            messages.append({"role": "assistant", "content": ex["assistant"]})
        messages.append({"role": "user", "content": prompt})
        return messages

    def _chat(self, messages: list[dict[str, str]], max_tokens: int = 1024) -> str:
        """Send messages to the configured provider, return raw completion text."""
        if self.provider == "groq":
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.1,
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content
        if self.provider == "k2think":
            return self._chat_k2think(messages)
        if self.provider == "ollama":
            return self._chat_ollama(messages, max_tokens=max_tokens)
        raise NotImplementedError

    def _chat_k2think(self, messages: list[dict[str, str]]) -> str:
        """Call the K2 Think API (OpenAI-compatible reasoning model).

        The model emits chain-of-thought inline terminated by ``</think>``
        (optionally an ``<answer>`` block); only the final answer is returned.
        """
        import time

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "temperature": 0.2,
            # Reasoning tokens count against the budget; leave headroom so the
            # code after </think> doesn't get truncated.
            "max_tokens": 16384,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            # The API gateway rejects default library user agents.
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 Edg/140.0.0.0"
            ),
        }
        attempts = 3
        last_exc: Exception | None = None
        for i in range(attempts):
            try:
                response = requests.post(
                    self.base_url, json=payload, headers=headers, timeout=self.timeout
                )
                if response.status_code >= 500 and i < attempts - 1:
                    time.sleep(1.5 * (i + 1))
                    continue
                response.raise_for_status()
                message = response.json()["choices"][0]["message"]
                # Some gateway responses omit "content" — text can land under
                # "reasoning_content" or "reasoning" (observed shapes).
                raw = (
                    message.get("content")
                    or message.get("reasoning_content")
                    or message.get("reasoning")
                    or ""
                )
                if not raw:
                    raise RuntimeError(
                        f"K2 Think returned an empty message: keys={list(message)}"
                    )
                return self._strip_reasoning(raw)
            except (requests.RequestException, RuntimeError) as exc:
                last_exc = exc
                if i < attempts - 1:
                    time.sleep(1.5 * (i + 1))
        raise RuntimeError(f"K2 Think request failed: {last_exc}") from last_exc

    @staticmethod
    def _strip_reasoning(content: str) -> str:
        """Drop K2 Think's inline chain-of-thought, keep the final answer."""
        i, j = content.find("<answer>"), content.rfind("</answer>")
        if i != -1 and j != -1 and j > i:
            return content[i + len("<answer>") : j].strip()
        end = content.rfind("</think>")
        if end != -1:
            return content[end + len("</think>") :].strip()
        return content.strip()

    def _chat_ollama(
        self, messages: list[dict[str, str]], max_tokens: int = 1024
    ) -> str:
        """Call Ollama's local chat API."""
        try:
            response = requests.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "temperature": 0.1,
                        "num_predict": max_tokens,
                    },
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            return data["message"]["content"]
        except requests.RequestException as e:
            raise RuntimeError(f"Ollama request failed: {e}") from e
        except (KeyError, TypeError) as e:
            raise RuntimeError("Ollama returned an unexpected response shape") from e

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
        return self._clean_code(self._chat(messages))

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

"""Augment text descriptions with linguistic variety.

A model trained on "60mm square plate" should also handle:
- "square plate, 60mm"
- "plate 60x60mm"
- "60 mm square panel"
- "a 60mm square aluminum plate"
"""

from __future__ import annotations

import random
import re


class DescriptionAugmenter:
    """Generates varied natural language descriptions for the same part."""

    PLATE_PHRASES = [
        "{w}x{h}mm {material}{name}, {t}mm thick",
        "{name} {w} by {h} mm, thickness {t}mm",
        "{t}mm thick {name}, dimensions {w}x{h}mm",
        "a {material}{name} measuring {w}mm wide, {h}mm tall, {t}mm thick",
        "{name}: {w}mm x {h}mm x {t}mm",
        "rectangular {name}, {w} by {h} millimeters, {t} thick",
        "{material}{name}, {w}x{h}mm, {t}mm",
        "{w} x {h} mm {name}, {t} mm thick",
    ]

    ROUND_PLATE_PHRASES = [
        "{d}mm diameter {material}{name}, {t}mm thick",
        "{material}{name}, diameter {d}mm, {t}mm thick",
        "circular {name}, {d}mm dia, {t}mm",
        "{name}: {d}mm round, {t}mm thick",
        "{d} mm {material}{name}, thickness {t}mm",
        "round {name} {d}mm OD, {t}mm",
    ]

    HOLE_PHRASES = [
        "{n} {type} holes on {pcd}mm bolt circle",
        "{n}x {type} clearance holes, PCD {pcd}mm",
        "{type} bolt pattern, {n} holes, {pcd}mm pitch circle",
        "{n} {type} mounting holes equally spaced on {pcd}mm diameter",
        "bolt circle: {n}x {type}, {pcd}mm PCD",
        "{n}x {type} on {pcd}mm PCD",
    ]

    SINGLE_HOLE_PHRASES = [
        "{n}x {d}mm through holes",
        "{n} holes, {d}mm diameter",
        "{n}x {d}mm clearance holes",
        "{n} {d}mm bores",
    ]

    CENTER_BORE_PHRASES = [
        "center bore {d}mm",
        "{d}mm central hole",
        "{d}mm bore in center",
        "{d}mm through-hole at center",
        "center opening {d}mm diameter",
        "central bore {d}mm dia",
    ]

    PLATE_NAMES = ["plate", "panel", "sheet", "blank", "base", "slab"]
    DISC_NAMES = ["disc", "disk", "round plate", "circular plate"]
    MATERIALS = ["", "aluminum ", "steel ", "stainless steel ", "mild steel ", "6061-T6 "]
    MANUFACTURING = ["", ", CNC machinable", ", for CNC milling", ", laser cut", ", waterjet cut"]

    BOLT_LABELS = {
        2.4: "M2", 2.8: "M2.5", 3.4: "M3", 4.5: "M4",
        5.5: "M5", 6.6: "M6", 8.4: "M8", 10.5: "M10",
        13.0: "M12", 17.5: "M16",
    }

    def _bolt_name(self, dia: float) -> str:
        best = min(self.BOLT_LABELS.keys(), key=lambda k: abs(k - dia))
        if abs(best - dia) < 0.5:
            return self.BOLT_LABELS[best]
        return f"{dia}mm"

    def augment(self, params: dict, part_type: str, num_variants: int = 5) -> list[str]:
        """Generate *num_variants* different text descriptions for the same params."""
        generators = {
            "rect": self._augment_rect,
            "rounded_rect": self._augment_rect,
            "circle": self._augment_circle,
            "plate": self._augment_rect,
            "disc": self._augment_circle,
            "flange": self._augment_circle,
            "spacer": self._augment_circle,
            "bushing": self._augment_circle,
            "washer": self._augment_circle,
        }
        gen_fn = generators.get(part_type, self._augment_rect)
        results: list[str] = []
        seen: set[str] = set()
        attempts = 0
        while len(results) < num_variants and attempts < num_variants * 5:
            attempts += 1
            text = gen_fn(params)
            text_lower = text.lower().strip()
            if text_lower not in seen:
                seen.add(text_lower)
                results.append(text)
        return results

    # ---- rect / rounded_rect variants ----

    def _augment_rect(self, params: dict) -> str:
        w = params.get("width", 50)
        h = params.get("height", 50)
        t = params.get("thickness", 5)
        cr = params.get("corner_r") or params.get("corner_radius")

        name = random.choice(self.PLATE_NAMES)
        material = random.choice(self.MATERIALS)

        base = random.choice(self.PLATE_PHRASES).format(
            w=self._dim(w), h=self._dim(h), t=self._dim(t),
            name=name, material=material,
        )
        if cr:
            base += random.choice([
                f", {self._dim(cr)}mm corner radius",
                f", R{self._dim(cr)}mm corners",
                f", rounded corners ({self._dim(cr)}mm)",
            ])

        parts = [base]
        parts.extend(self._hole_phrases(params))
        text = ", ".join(parts) if len(parts) > 1 else parts[0]

        if random.random() < 0.25:
            text += random.choice(self.MANUFACTURING)

        return text.strip().rstrip(",").strip()

    # ---- circle variants ----

    def _augment_circle(self, params: dict) -> str:
        d = params.get("diameter") or params.get("od", 50)
        t = params.get("thickness") or params.get("length", 5)

        name = random.choice(self.DISC_NAMES)
        material = random.choice(self.MATERIALS)

        base = random.choice(self.ROUND_PLATE_PHRASES).format(
            d=self._dim(d), t=self._dim(t),
            name=name, material=material,
        )

        parts = [base]
        parts.extend(self._hole_phrases(params))
        text = ", ".join(parts) if len(parts) > 1 else parts[0]

        if random.random() < 0.25:
            text += random.choice(self.MANUFACTURING)

        return text.strip().rstrip(",").strip()

    # ---- hole description fragments ----

    def _hole_phrases(self, params: dict) -> list[str]:
        frags: list[str] = []

        # center bore
        bore = params.get("bore") or params.get("bore_dia") or params.get("hole_dia_center")
        if bore:
            frags.append(random.choice(self.CENTER_BORE_PHRASES).format(d=self._dim(bore)))

        # bolt pattern
        bolt_dia = params.get("bolt_dia")
        bolt_count = params.get("bolt_count") or params.get("count")
        pcd = params.get("pcd") or params.get("bolt_pcd")
        if bolt_dia and bolt_count and pcd:
            btype = self._bolt_name(bolt_dia)
            frags.append(random.choice(self.HOLE_PHRASES).format(
                n=bolt_count, type=btype, pcd=self._dim(pcd),
            ))

        # inner / outer bolt circles
        for prefix in ("inner_", "outer_"):
            bd = params.get(f"{prefix}bolt_dia")
            bc = params.get(f"{prefix}count") or params.get(f"{prefix}bolt_count")
            pp = params.get(f"{prefix}pcd")
            if bd and bc and pp:
                btype = self._bolt_name(bd)
                label = "inner" if prefix == "inner_" else "outer"
                frags.append(f"{label} ring: " + random.choice(self.HOLE_PHRASES).format(
                    n=bc, type=btype, pcd=self._dim(pp),
                ))

        # generic hole count (non-patterned)
        hole_dia = params.get("hole_dia")
        hole_count = params.get("hole_count")
        if hole_dia and hole_count and not pcd:
            frags.append(random.choice(self.SINGLE_HOLE_PHRASES).format(
                n=hole_count, d=self._dim(hole_dia),
            ))

        # blind holes
        depth = params.get("depth") or params.get("hole_depth")
        if depth:
            if frags:
                frags[-1] = frags[-1].replace("through", "blind")
            frags.append(f"{self._dim(depth)}mm deep")

        return frags

    # ---- helpers ----

    @staticmethod
    def _dim(v: float) -> str:
        """Format dimension, dropping trailing .0"""
        if isinstance(v, float) and v == int(v):
            return str(int(v))
        return f"{v:.1f}" if isinstance(v, float) else str(v)

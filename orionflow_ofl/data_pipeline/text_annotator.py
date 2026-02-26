"""Generate text descriptions for OFL scripts at multiple detail levels."""

from __future__ import annotations

import ast
import random
import re


# synonym pools
_PLATE_WORDS = ["plate", "panel", "sheet", "blank", "slab"]
_DISC_WORDS = ["disc", "disk", "circular plate", "round plate"]
_HOLE_WORDS = ["holes", "bores", "openings"]
_MOUNT_WORDS = ["mounting", "fastening", "attachment", "fixing"]


class TextAnnotator:
    """Generates text descriptions for OFL scripts."""

    def annotate_from_code(self, ofl_code: str) -> list[str]:
        """Parse OFL code and generate 5 text descriptions (vague -> expert)."""
        info = self._parse_code(ofl_code)
        return self._generate_descriptions(info)

    def annotate_from_params(self, params: dict, part_type: str) -> list[str]:
        """Generate descriptions from known parameters."""
        info = {"part_type": part_type, **params}
        return self._generate_descriptions(info)

    # ------------------------------------------------------------------
    # code parsing
    # ------------------------------------------------------------------
    def _parse_code(self, code: str) -> dict:
        info: dict = {
            "profile": None,
            "width": None,
            "height": None,
            "diameter": None,
            "corner_radius": None,
            "thickness": None,
            "holes": [],
        }
        # extract variable assignments
        var_values = self._extract_variables(code)

        # detect profile
        if ".rounded_rect(" in code:
            info["profile"] = "rounded_rect"
        elif ".rect(" in code:
            info["profile"] = "rect"
        elif ".circle(" in code:
            info["profile"] = "circle"

        # resolve dimensions from code
        m = re.search(r"\.rect\(([^)]+)\)", code)
        if m:
            args = [a.strip() for a in m.group(1).split(",")]
            info["width"] = self._resolve(args[0], var_values)
            if len(args) > 1:
                info["height"] = self._resolve(args[1], var_values)

        m = re.search(r"\.rounded_rect\(([^)]+)\)", code)
        if m:
            args = [a.strip() for a in m.group(1).split(",")]
            info["width"] = self._resolve(args[0], var_values)
            if len(args) > 1:
                info["height"] = self._resolve(args[1], var_values)
            if len(args) > 2:
                info["corner_radius"] = self._resolve(args[2], var_values)

        m = re.search(r"\.circle\(([^)]+)\)", code)
        if m:
            info["diameter"] = self._resolve(m.group(1).strip(), var_values)

        m = re.search(r"\.extrude\(([^)]+)\)", code)
        if m:
            info["thickness"] = self._resolve(m.group(1).strip(), var_values)

        # parse holes
        hole_blocks = re.findall(
            r"Hole\(([^)]+)\)(.*?)(?=\n\s*\))", code, re.DOTALL,
        )
        for dia_str, body in hole_blocks:
            hole: dict = {
                "diameter": self._resolve(dia_str.strip(), var_values),
                "count": 0,
                "through": ".through()" in body,
                "depth": None,
                "label": None,
                "pattern": "manual",
            }
            # count .at() calls
            hole["count"] += len(re.findall(r"\.at\(", body))
            # circular pattern
            m_circ = re.search(r"\.at_circular\([^,]+,\s*count\s*=\s*(\d+)", body)
            if m_circ:
                hole["count"] += int(m_circ.group(1))
                hole["pattern"] = "circular"
                m_pcd = re.search(r"\.at_circular\(([^,]+)", body)
                if m_pcd:
                    radius = self._resolve(m_pcd.group(1).strip(), var_values)
                    if radius is not None:
                        hole["pcd"] = round(radius * 2, 1)
            # depth
            m_depth = re.search(r"\.to_depth\(([^)]+)\)", body)
            if m_depth:
                hole["depth"] = self._resolve(m_depth.group(1).strip(), var_values)
            # label
            m_label = re.search(r'\.label\("([^"]+)"\)', body)
            if m_label:
                hole["label"] = m_label.group(1)

            if hole["count"] > 0:
                info["holes"].append(hole)

        return info

    def _extract_variables(self, code: str) -> dict:
        vals = {}
        for line in code.splitlines():
            line = line.strip()
            m = re.match(r"^(\w+)\s*=\s*(.+)$", line)
            if m:
                name = m.group(1)
                try:
                    vals[name] = eval(m.group(2), {"__builtins__": {}}, vals)
                except Exception:
                    pass
        return vals

    def _resolve(self, expr: str, var_values: dict) -> float | None:
        try:
            return float(eval(expr, {"__builtins__": {}}, var_values))
        except Exception:
            return None

    # ------------------------------------------------------------------
    # description generation
    # ------------------------------------------------------------------
    def _generate_descriptions(self, info: dict) -> list[str]:
        return [
            self._level_1_vague(info),
            self._level_2_basic(info),
            self._level_3_medium(info),
            self._level_4_detailed(info),
            self._level_5_expert(info),
        ]

    def _shape_word(self, info: dict) -> str:
        profile = info.get("profile")
        if profile == "circle":
            return random.choice(_DISC_WORDS)
        return random.choice(_PLATE_WORDS)

    def _is_square(self, info: dict) -> bool:
        w = info.get("width")
        h = info.get("height")
        return w is not None and h is not None and abs(w - h) < 0.1

    def _total_holes(self, info: dict) -> int:
        return sum(h.get("count", 0) for h in info.get("holes", []))

    def _bolt_size_guess(self, dia: float | None) -> str | None:
        if dia is None:
            return None
        clearance_map = {
            2.4: "M2", 2.6: "M2.5", 3.4: "M3", 4.5: "M4",
            5.5: "M5", 6.6: "M6", 8.4: "M8", 10.5: "M10",
            13.0: "M12", 17.5: "M16",
        }
        best = min(clearance_map.keys(), key=lambda k: abs(k - dia))
        if abs(best - dia) < 0.5:
            return clearance_map[best]
        return None

    # --- levels ---

    def _level_1_vague(self, info: dict) -> str:
        word = self._shape_word(info)
        n = self._total_holes(info)
        if n > 0:
            return f"A {word} with some {random.choice(_HOLE_WORDS)}"
        return f"A flat {word}"

    def _level_2_basic(self, info: dict) -> str:
        profile = info.get("profile", "rect")
        n = self._total_holes(info)
        if profile == "circle":
            base = f"A circular {random.choice(_PLATE_WORDS)}"
        elif self._is_square(info):
            base = f"A square {random.choice(_PLATE_WORDS)}"
        else:
            base = f"A rectangular {random.choice(_PLATE_WORDS)}"

        if info.get("corner_radius"):
            base += " with rounded corners"

        if n == 0:
            return base
        if n == 1:
            return f"{base} with a center hole"
        return f"{base} with {n} {random.choice(_MOUNT_WORDS)} {random.choice(_HOLE_WORDS)}"

    def _level_3_medium(self, info: dict) -> str:
        parts = []
        profile = info.get("profile", "rect")
        w, h, d = info.get("width"), info.get("height"), info.get("diameter")
        t = info.get("thickness")

        if profile == "circle" and d:
            parts.append(f"{d:.0f}mm diameter {random.choice(_DISC_WORDS)}")
        elif self._is_square(info) and w:
            parts.append(f"{w:.0f}mm square {random.choice(_PLATE_WORDS)}")
        elif w and h:
            parts.append(f"{w:.0f}x{h:.0f}mm {random.choice(_PLATE_WORDS)}")

        if t:
            parts.append(f"{t:.0f}mm thick")

        n = self._total_holes(info)
        if n > 0:
            parts.append(f"with {n} holes")
        return ", ".join(parts) if parts else "A part"

    def _level_4_detailed(self, info: dict) -> str:
        parts = []
        profile = info.get("profile", "rect")
        w, h, d = info.get("width"), info.get("height"), info.get("diameter")
        t = info.get("thickness")
        cr = info.get("corner_radius")

        if profile == "circle" and d:
            parts.append(f"{d:.0f}mm diameter {random.choice(_DISC_WORDS)}")
        elif self._is_square(info) and w:
            parts.append(f"{w:.0f}mm square {random.choice(_PLATE_WORDS)}")
        elif w and h:
            parts.append(f"{w:.0f}x{h:.0f}mm {random.choice(_PLATE_WORDS)}")

        if t:
            parts.append(f"{t:.0f}mm thick")
        if cr:
            parts.append(f"{cr:.0f}mm corner radius")

        for hole in info.get("holes", []):
            hdia = hole.get("diameter")
            count = hole.get("count", 0)
            bolt = self._bolt_size_guess(hdia)
            desc = f"{count}x"
            if bolt:
                desc += f" {bolt} clearance"
            elif hdia:
                desc += f" {hdia:.1f}mm"
            if hole.get("through"):
                desc += " through holes"
            elif hole.get("depth"):
                desc += f" blind holes ({hole['depth']:.0f}mm deep)"
            else:
                desc += " holes"
            if hole.get("pattern") == "circular" and hole.get("pcd"):
                desc += f" on {hole['pcd']:.0f}mm PCD"
            parts.append(desc)

        return ", ".join(parts) if parts else "A machined part"

    def _level_5_expert(self, info: dict) -> str:
        base = self._level_4_detailed(info)
        w = info.get("width")
        h = info.get("height")
        d = info.get("diameter")
        t = info.get("thickness")

        dims = ""
        if w and h and t:
            dims = f"{w:.0f}x{h:.0f}x{t:.0f}mm"
        elif d and t:
            dims = f"\u00d8{d:.0f}x{t:.0f}mm"

        material = random.choice(["6061-T6 aluminum", "mild steel", "304 stainless"])
        process = random.choice(["CNC machinable", "laser-cut and drilled", "waterjet + CNC"])

        suffix_parts = []
        if dims:
            suffix_parts.append(dims)
        suffix_parts.append(material)
        suffix_parts.append(process)
        return f"{base}, {', '.join(suffix_parts)}"

"""Material densities and manufacturing processes, from what a BOM says.

Densities are nominal handbook values (kg/m^3). JIS designations are listed
because robot BOMs from Japanese suppliers use them (A2024, SUS304, S45C ...);
generic names fall back to interface_check's table. A material that is not
known, or a cell that names two materials ("A2024 / PLA_BLACK" — machined or
printed), gives **no** density: the mass is left unknown and the reason
stated, never filled with a default.
"""
from __future__ import annotations

import re

JIS = {
    # aluminium alloys
    "a1050": 2710, "a2017": 2790, "a2024": 2780, "a5052": 2680, "a6061": 2700, "a6063": 2690, "a7075": 2810,
    # stainless and steels
    "sus303": 7930, "sus304": 7930, "sus316l": 7980, "sus316": 7980, "sus440c": 7780, "sus": 7930,
    "s45c": 7850, "s50c": 7850, "scm435": 7850, "scm440": 7850, "sks3": 7850, "suj2": 7830, "ss400": 7850,
    "spcc": 7850, "sk4": 7850,
    # copper alloys
    "c3604": 8500, "brass": 8500, "phosphor bronze": 8800,
    # polymers commonly printed or machined
    "pla": 1240, "petg": 1270, "abs": 1050, "asa": 1070, "pom": 1410, "nylon": 1140, "pa12": 1010, "tpu": 1210,
}
PLASTICS = ("pla", "petg", "abs", "asa", "pom", "nylon", "pa12", "pa6", "tpu", "resin", "delrin", "acetal",
            "polycarbonate", "acrylic")


def density(material: str | None) -> tuple[float | None, str]:
    """(kg/m^3 or None, reason)."""
    m = (material or "").strip().lower()
    if not m or m in ("n/a", "na", "-", "none"):
        return None, "no material given"
    if re.search(r"\s/\s|\bor\b", m):
        return None, f"two materials listed ({material}): mass depends on which is used"
    key = re.sub(r"[_\s-]+(black|white|red|blue|grey|gray|natural|clear)$", "", m)
    for name, rho in sorted(JIS.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", key):
            return float(rho), f"{name.upper()} {rho} kg/m³ (handbook)"
    try:
        from interface_check.urdf_drift import density_for
        rho = density_for(m)
        if rho:
            return float(rho), f"{material}: {rho} kg/m³ (handbook)"
    except Exception:  # noqa: BLE001
        pass
    return None, f"density of '{material}' is not known"


def is_plastic(material: str | None, process: str | None = None) -> bool:
    m = (material or "").lower()
    return (process or "").upper() in ("FDM", "SLA", "SLS") or any(p in m for p in PLASTICS)


def process_from_type(t: str | None) -> str | None:
    """BOM TYPE / make-buy cell -> process."""
    s = (t or "").strip().lower()
    if not s:
        return None
    printed = bool(re.search(r"3d|print|fdm|sla|sls", s))
    machined = bool(re.search(r"machin|cnc|mill|turn", s))
    if printed and machined:
        return "CNC or FDM"
    if printed:
        return "FDM"
    if machined:
        return "CNC"
    if re.search(r"standard|purchas|buy|cots|off.the.shelf|catalog", s):
        return "purchased"
    if re.search(r"sheet", s):
        return "sheet metal"
    if re.search(r"mold|mould|inject", s):
        return "molded"
    return None

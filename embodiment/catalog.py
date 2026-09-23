"""Materials and actuators, read from the existing knowledge base.

`orion_physical_ai/knowledge/{materials,parts_db}.json` is where OrionFlow
already keeps densities and part datasheets; the embodiment compiler reads
the same files rather than restating any number.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

KNOWLEDGE = Path(__file__).resolve().parent.parent / "orion_physical_ai" / "knowledge"
G = 9.80665          # m/s^2, standard gravity (also kgf -> N)


@lru_cache(maxsize=None)
def _load(name: str) -> dict:
    return json.loads((KNOWLEDGE / name).read_text(encoding="utf-8"))


def material(key: str) -> dict:
    mats = _load("materials.json")
    if key not in mats:
        raise KeyError(f"unknown material {key!r}; known: {sorted(mats)}")
    return mats[key]


def actuator(key: str) -> dict:
    parts = _load("parts_db.json")
    if key not in parts or parts[key].get("category") != "motor":
        raise KeyError(f"unknown actuator {key!r}")
    return parts[key]


def actuator_limits(key: str) -> dict:
    """Stall torque (N m) and no-load speed (rad/s) from the datasheet.

    Servo datasheets quote torque in kg cm and speed as seconds per 60
    degrees, at one supply voltage; both are taken at the same voltage.
    """
    a = actuator(key)
    missing = [k for k in ("torque_kg_cm", "speed_s_per_60deg") if k not in a]
    if missing:
        raise KeyError(f"actuator {key!r} lacks {missing}: its limits would be invented")
    return {
        "effort_nm": a["torque_kg_cm"] * G / 100.0,
        "velocity_rad_s": (math.pi / 3) / a["speed_s_per_60deg"],
        "mass_kg": a["mass_g"] / 1000.0,
        "rated_voltage_v": a.get("rated_voltage_v"),
        "source": f"parts_db.json:{key}",
    }

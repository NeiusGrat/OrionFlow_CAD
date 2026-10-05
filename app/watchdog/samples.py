"""Sample projects: a synthetic robot assembly with known, seeded problems,
submitted to the assembly engine as the caller's own analysis.

Each sample is built from ``interface_check.synth`` (exact ground truth) with
two seeded errors merged into one revision, and the clean assembly as the
previous revision, so one run exercises interfaces, BOM or URDF drift and the
revision diff together.
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

SAMPLES = {
    "robot_joint": {"label": "Sample: bearing joint + URDF", "assembly": "bearing_joint",
                    "mutations": ["bj_bore_+0.5", "bj_urdf_com"],
                    "about": "608 bearing seat, base flange and the robot model that describes them"},
    "chassis": {"label": "Sample: rover chassis + BOM", "assembly": "chassis",
                "mutations": ["ch_bom_qty_standoff", "ch_cover_hole_0.8"],
                "about": "Chassis plate, brackets, standoffs and cover against a purchasing BOM"},
    "motor_mount": {"label": "Sample: NEMA 17 motor mount", "assembly": "motor_mount",
                    "mutations": ["mm_corner_1.0", "mm_frame_tap_m3"],
                    "about": "Stepper on a plate, plate bolted to a frame with M3 and M4 hardware"},
}


def submit(name: str, user_id: str) -> dict:
    """Build the sample, upload it as ``user_id`` and create the analysis job."""
    from interface_check.service import api as ic
    from interface_check.service.auth import _with_plan
    from interface_check.service.dispatch import context
    from interface_check.synth import MUTATIONS, build

    s = SAMPLES[name]
    params: dict = {}
    for mid in s["mutations"]:
        params.update(next(m for m in MUTATIONS if m.id == mid).params)
    ctx = context()
    user = _with_plan(user_id, False)
    upload_id = uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix="watchdog_sample_") as tmp:
        cur = build(s["assembly"], params, Path(tmp) / "rev_b", f"{s['assembly']}_revB")
        prev = build(s["assembly"], {}, Path(tmp) / "rev_a", f"{s['assembly']}_revA")
        files = {"step": cur["step"], "prev_step": prev["step"]}
        for k in ("bom", "urdf", "urdf_map"):
            if k in cur:
                files[k] = cur[k]
        if "bom" in prev:
            files["prev_bom"] = prev["bom"]
        for kind, path in files.items():
            ctx.storage.put_bytes(f"uploads/{user.id}/{upload_id}/{kind}/{Path(path).name}",
                                  Path(path).read_bytes())
    return ic._public(ic._create(user, upload_id, s["label"], None, None, None))

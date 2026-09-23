"""Exact mass properties from the B-rep, via OpenCASCADE.

Volume, centre of mass and inertia come from `BRepGProp` integrating over
the solid itself - not from a tessellation, and not from a bounding box.
OpenCASCADE integrates at unit density, so each component is scaled by its
own density and the link's properties are the parallel-axis sum.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps


@dataclass
class MassProps:
    mass_kg: float
    com_m: np.ndarray          # in the link frame
    inertia_kg_m2: np.ndarray  # 3x3, about the centre of mass, link-frame axes
    volume_m3: float


def solid_props(shape, density_kg_m3: float) -> MassProps:
    """Mass properties of one placed solid (millimetres) at a density."""
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape.wrapped, props)
    vol_mm3 = props.Mass()
    if vol_mm3 <= 0:
        raise ValueError(f"solid has non-positive volume ({vol_mm3} mm^3)")
    c = props.CentreOfMass()
    M = props.MatrixOfInertia()           # about the centre of mass, density 1, mm^5
    I_mm5 = np.array([[M.Value(i, j) for j in (1, 2, 3)] for i in (1, 2, 3)])
    rho_kg_mm3 = density_kg_m3 * 1e-9
    return MassProps(
        mass_kg=vol_mm3 * rho_kg_mm3,
        com_m=np.array([c.X(), c.Y(), c.Z()]) * 1e-3,
        inertia_kg_m2=I_mm5 * rho_kg_mm3 * 1e-6,
        volume_m3=vol_mm3 * 1e-9,
    )


def combine(parts: list[MassProps]) -> MassProps:
    """One rigid body from several: summed mass, parallel-axis inertia."""
    m = sum(p.mass_kg for p in parts)
    com = sum(p.mass_kg * p.com_m for p in parts) / m
    I = np.zeros((3, 3))
    for p in parts:
        d = p.com_m - com
        I += p.inertia_kg_m2 + p.mass_kg * (np.dot(d, d) * np.eye(3) - np.outer(d, d))
    return MassProps(m, com, (I + I.T) / 2, sum(p.volume_m3 for p in parts))

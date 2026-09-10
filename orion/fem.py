"""A small structural solver: 2D Timoshenko frames, by direct stiffness.

This exists because of a hole the search found. Asked to lighten a bracket
carrying 400 N, it thinned the base plate to 1 mm — correctly, because the only
declared evidence was a cantilever formula for the *upright*, and nothing in
the system read the base at all. A parameter nothing reads is free mass.

**Why a frame and not tetrahedra.** The obvious "light FEA" is a coarse 3D mesh
of linear tetrahedra, and it would be a step backwards. Measured on a
100x10x10 cantilever, linear tets at a 5 mm mesh underpredict tip deflection by
53% and mid-span stress by 69%; the closed form already in :mod:`orion.calc` is
exact for the same case. Replacing an exact answer with a 53% error and calling
it simulation is the failure this file is written to avoid.

A two-node Timoshenko beam element has no such error. Its stiffness matrix is
the exact solution of the beam equation for a prismatic member, so a frame of
them is exact at the nodes for any structure actually made of prismatic
members — which is what an L-bracket is. There is no mesh, no element size to
choose, no convergence study, and the whole L-bracket problem is twelve degrees
of freedom. It solves in microseconds with :func:`numpy.linalg.solve`.

**What it therefore cannot do**, stated here rather than discovered later:

* no stress concentration — a frame has no notion of a fillet radius or a hole,
  so a reported stress is the nominal section stress and a real part will peak
  higher at every re-entrant corner
* no plate or shell behaviour — a wide base plate carrying a corner load
  distributes it two-dimensionally, and modelling it as a beam of the full
  width is conservative in some geometries and not in others (see
  :func:`l_bracket_frame`)
* no contact, no bolt preload, no buckling, no plasticity, no pressure
* nothing three-dimensional: no bore hoop stress, so a bearing housing and a
  manifold remain exactly as unjudged as they were

**Units.** Newtons and millimetres throughout, so stresses come out in MPa and
E is given in MPa. The same convention as :mod:`orion.calc`, deliberately: two
unit systems in one codebase is a defect waiting for a deadline.

No new dependency. NumPy only — the systems here are small and dense, and
pulling in a sparse solver for a 12x12 matrix would be silly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

#: Timoshenko shear coefficient for a rectangle. The same 5/6 that
#: ``calc.beam_bending`` uses; they must agree or a frame of one member would
#: disagree with the closed form it is supposed to reproduce.
KAPPA_RECT = 5.0 / 6.0

#: Degrees of freedom per node: translation x, translation z, rotation about y.
DOF = 3


class FrameError(ValueError):
    """A model that cannot be solved, and why."""


@dataclass(frozen=True)
class Section:
    """A prismatic rectangular cross-section.

    ``width`` is across the bending axis and ``height`` is in the plane of
    bending, matching :func:`orion.calc.beam_bending` — so ``I = w*h**3/12``
    and the height is the dimension the load bends the member *through*.
    """

    width: float
    height: float

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise FrameError("section dimensions must be positive")

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def inertia(self) -> float:
        return self.width * self.height ** 3 / 12.0

    @property
    def extreme_fibre(self) -> float:
        return self.height / 2.0


@dataclass(frozen=True)
class Member:
    """One prismatic element between two nodes."""

    node_a: int
    node_b: int
    section: Section
    #: A label a reader can recognise — "base", "upright". It travels onto the
    #: results, because "member 1 is overstressed" helps nobody.
    name: str = ""


@dataclass
class Frame:
    """Nodes, members, supports and loads. Everything the solver needs."""

    #: ``[(x, z), ...]`` in millimetres.
    nodes: list
    members: list
    #: Node index to the DOF it restrains: any of ``"x"``, ``"z"``, ``"r"``.
    supports: dict = field(default_factory=dict)
    #: Node index to ``(fx, fz, moment)`` in N and N·mm.
    loads: dict = field(default_factory=dict)
    #: MPa, and Poisson's ratio.
    modulus: float = 205000.0
    poisson: float = 0.29

    @property
    def shear_modulus(self) -> float:
        return self.modulus / (2.0 * (1.0 + self.poisson))


@dataclass
class MemberResult:
    """What one member ended up carrying."""

    name: str
    index: int
    axial_n: float
    shear_n: float
    #: The larger end moment, which for a prismatic member with end loads only
    #: is where the peak bending stress is.
    moment_nmm: float
    bending_mpa: float
    axial_mpa: float

    @property
    def stress_mpa(self) -> float:
        """Nominal peak stress: bending plus axial, same fibre.

        Nominal, and the word matters. A frame has no fillet and no hole, so
        this is the stress in the plain section and a real part peaks higher
        wherever the geometry changes.
        """
        return abs(self.bending_mpa) + abs(self.axial_mpa)


@dataclass
class Solution:
    """Displacements, member forces, and the worst of them."""

    #: Per node, ``(dx, dz, rotation)`` in mm and radians.
    displacements: np.ndarray
    members: list
    frame: Frame = field(repr=False, default=None)

    def deflection_at(self, node: int) -> float:
        """Resultant translation at one node, in mm."""
        dx, dz = self.displacements[node][0], self.displacements[node][1]
        return float(math.hypot(dx, dz))

    @property
    def max_deflection_mm(self) -> float:
        return max((self.deflection_at(i)
                    for i in range(len(self.displacements))), default=0.0)

    @property
    def max_stress_mpa(self) -> float:
        return max((m.stress_mpa for m in self.members), default=0.0)

    @property
    def worst(self) -> Optional[MemberResult]:
        """The member carrying the highest nominal stress.

        The useful half of the answer: an engineer wants to know *which* part
        of the bracket is the problem, not only that there is one.
        """
        return max(self.members, key=lambda m: m.stress_mpa, default=None)


def _element_stiffness(length: float, section: Section, modulus: float,
                       shear_modulus: float) -> np.ndarray:
    """Local 6x6 stiffness for a 2D Timoshenko beam-column.

    ``phi`` is the shear-flexibility parameter, ``12EI/(kappa*G*A*L^2)``. At
    ``phi = 0`` every term below reduces to the Euler-Bernoulli element, which
    is the check that this is the same physics the closed form uses — and the
    same correction that was missing from ``calc.beam_bending`` until it was
    found underpredicting a stubby beam's deflection by 16%.
    """
    if length <= 0:
        raise FrameError("a member must have positive length")
    area, inertia = section.area, section.inertia
    ei, ea = modulus * inertia, modulus * area
    phi = 12.0 * ei / (KAPPA_RECT * shear_modulus * area * length ** 2)

    a = ea / length
    b = 12.0 * ei / ((1.0 + phi) * length ** 3)
    c = 6.0 * ei / ((1.0 + phi) * length ** 2)
    d = (4.0 + phi) * ei / ((1.0 + phi) * length)
    e = (2.0 - phi) * ei / ((1.0 + phi) * length)

    return np.array([
        [a, 0, 0, -a, 0, 0],
        [0, b, c, 0, -b, c],
        [0, c, d, 0, -c, e],
        [-a, 0, 0, a, 0, 0],
        [0, -b, -c, 0, b, -c],
        [0, c, e, 0, -c, d],
    ], dtype=float)


def _rotation(dx: float, dz: float, length: float) -> np.ndarray:
    """Local-to-global transform for a member at an arbitrary angle."""
    c, s = dx / length, dz / length
    r = np.zeros((6, 6))
    block = np.array([[c, s, 0.0], [-s, c, 0.0], [0.0, 0.0, 1.0]])
    r[:3, :3] = block
    r[3:, 3:] = block
    return r


def solve(frame: Frame) -> Solution:
    """Solve a frame by direct stiffness. Pure NumPy, dense, exact at nodes.

    Raises :class:`FrameError` when the structure is a mechanism — a singular
    stiffness matrix means the supports do not remove every rigid-body motion,
    which the report's well-posedness gate names as the first thing to check
    and which otherwise returns numbers that look like an answer.
    """
    n = len(frame.nodes)
    if n < 2 or not frame.members:
        raise FrameError("a frame needs at least two nodes and one member")

    size = n * DOF
    stiffness = np.zeros((size, size))
    geometry = []

    for member in frame.members:
        ax, az = frame.nodes[member.node_a]
        bx, bz = frame.nodes[member.node_b]
        dx, dz = bx - ax, bz - az
        length = math.hypot(dx, dz)
        if length <= 0:
            raise FrameError(f"member {member.name or ''} has zero length")
        local = _element_stiffness(length, member.section, frame.modulus,
                                  frame.shear_modulus)
        rot = _rotation(dx, dz, length)
        stiffness_global = rot.T @ local @ rot
        geometry.append((member, length, local, rot))

        dofs = _dofs(member.node_a) + _dofs(member.node_b)
        for i, gi in enumerate(dofs):
            for j, gj in enumerate(dofs):
                stiffness[gi, gj] += stiffness_global[i, j]

    forces = np.zeros(size)
    for node, (fx, fz, moment) in (frame.loads or {}).items():
        forces[node * DOF:node * DOF + 3] += (fx, fz, moment)

    fixed = set()
    for node, which in (frame.supports or {}).items():
        for letter in str(which):
            offset = {"x": 0, "z": 1, "r": 2}.get(letter)
            if offset is None:
                raise FrameError(f"unknown restraint {letter!r}; use x, z or r")
            fixed.add(node * DOF + offset)
    free = [i for i in range(size) if i not in fixed]
    if not free:
        raise FrameError("every degree of freedom is restrained")

    sub = stiffness[np.ix_(free, free)]
    # A singular system means a mechanism, not a hard problem. Say which.
    if not np.all(np.isfinite(sub)) or \
            np.linalg.matrix_rank(sub) < len(free):
        raise FrameError(
            "the structure is a mechanism: the supports do not remove every "
            "rigid-body motion, so there is no static solution")

    displacement = np.zeros(size)
    displacement[free] = np.linalg.solve(sub, forces[free])

    results = []
    for index, (member, length, local, rot) in enumerate(geometry):
        dofs = _dofs(member.node_a) + _dofs(member.node_b)
        end_forces = local @ rot @ displacement[dofs]
        axial = float(end_forces[0])
        shear = float(end_forces[1])
        moment = max(abs(float(end_forces[2])), abs(float(end_forces[5])))
        section = member.section
        results.append(MemberResult(
            name=member.name or f"member {index}",
            index=index,
            axial_n=-axial,
            shear_n=shear,
            moment_nmm=moment,
            bending_mpa=moment * section.extreme_fibre / section.inertia,
            axial_mpa=-axial / section.area,
        ))

    return Solution(displacements=displacement.reshape(n, DOF),
                    members=results, frame=frame)


def _dofs(node: int) -> list:
    return [node * DOF, node * DOF + 1, node * DOF + 2]


# --------------------------------------------------------------------------- #
# The models this system can build
# --------------------------------------------------------------------------- #


def cantilever_frame(length_mm: float, width_mm: float, height_mm: float,
                     load_n: float, modulus: float,
                     poisson: float) -> Frame:
    """One member, fixed at one end, loaded transversely at the other.

    Here to be checked against :func:`orion.calc.beam_bending` rather than to
    be used: a frame of one member must reproduce the closed form exactly, and
    if it ever stops doing so one of the two is wrong.
    """
    return Frame(
        nodes=[(0.0, 0.0), (length_mm, 0.0)],
        members=[Member(0, 1, Section(width_mm, height_mm), "beam")],
        supports={0: "xzr"},
        loads={1: (0.0, -abs(load_n), 0.0)},
        modulus=modulus, poisson=poisson,
    )


def l_bracket_frame(base_length: float, base_width: float,
                    base_thickness: float, upright_height: float,
                    upright_width: float, upright_thickness: float,
                    load_n: float, modulus: float, poisson: float) -> Frame:
    """An L-bracket as two members meeting at a rigid corner.

    Three nodes: the far end of the base, which is where it bolts down and is
    taken as fully fixed; the corner; and the top of the upright, where the
    load acts perpendicular to the upright's face.

    **This is the whole point of the file.** The single-cantilever closed form
    reads only the upright, so the base plate could be thinned to nothing with
    nothing objecting. Here the moment at the top of the upright travels down
    it, through the corner, and along the base as bending — so the base's own
    section carries it, and ``base_thickness`` appears cubed in the answer the
    way it does in the real part.

    Two modelling choices worth disagreeing with:

    *The base is one beam of its full width.* A real base plate spreads a corner
    load two-dimensionally and a beam of the full width is stiffer than that,
    so this under-predicts base deflection for a wide, short base. It is the
    same idealisation the closed form already makes for the upright, and
    replacing it needs plate elements rather than a bigger frame.

    *The far end is fully fixed.* Real bolts are a finite number of finite
    stiffnesses, and a fully fixed end is stiffer than any of them, so the
    stresses here are lower at the support than a bolted joint would give. The
    report is explicit that this is where real verdicts go wrong; it is stated
    on the result rather than buried.
    """
    if upright_height <= base_thickness:
        raise FrameError("the upright must rise above the base")
    return Frame(
        nodes=[
            (0.0, 0.0),                                   # bolted end
            (max(base_length - upright_thickness / 2.0, 1e-6), 0.0),  # corner
            (max(base_length - upright_thickness / 2.0, 1e-6),
             upright_height - base_thickness),            # top of upright
        ],
        members=[
            Member(0, 1, Section(base_width, base_thickness), "base"),
            Member(1, 2, Section(upright_width, upright_thickness), "upright"),
        ],
        supports={0: "xzr"},
        # Perpendicular to the upright's face, which is along the base.
        loads={2: (abs(load_n), 0.0, 0.0)},
        modulus=modulus, poisson=poisson,
    )

"""Mutation: a dimension derived from wall-clock time. Must fail
tier1.rebuild_deterministic when built twice -- never averaged away as
noise (§13.3: "any non-determinism is a bug in the harness, not noise to
be averaged away")."""

from orionflow_ofl import *
import time

_jitter = (time.time() * 1000) % 1.0

part = (
    Sketch(Plane.XY)
    .rect(50, 30)
    .extrude(5 + _jitter)
)

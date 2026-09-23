"""robocheck: is this robot description physically valid?

Checks a URDF or MJCF file the way a simulator will use it: the structure as
written, the inertia no rigid body could have, the mass that does not match
its own geometry, the parts that overlap at rest, and whether the robot
settles under gravity without the simulation blowing up.

    python -m robocheck path/to/robot.urdf
    python -m robocheck --robot-descriptions            # every public model

Standalone: it imports nothing from the rest of this repository.
"""
from .check import check_file
from .findings import Finding, Report

__all__ = ["check_file", "Finding", "Report"]

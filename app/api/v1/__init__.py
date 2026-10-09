"""
API v1 router aggregation.

All v1 endpoints are mounted under /api/v1/
"""

from fastapi import APIRouter

from app.api.v1 import (
    agent,
    artifacts,
    auth,
    users,
    designs,
    billing,
    editing,
    fai,
    jobs,
    sessions,
    studio,
    topology,
    waitlist,
    demo,
    watchdog,
)

api_router = APIRouter(prefix="/api/v1")

# Mount sub-routers
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(designs.router, prefix="/designs", tags=["Designs"])
api_router.include_router(billing.router, prefix="/billing", tags=["Billing"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["Jobs"])
api_router.include_router(waitlist.router, prefix="/waitlist", tags=["Waitlist"])
api_router.include_router(demo.router, prefix="/demo-requests", tags=["Demo"])
api_router.include_router(agent.router, prefix="/agent", tags=["Agent"])
api_router.include_router(studio.router, prefix="/studio", tags=["Studio"])
# The workflow with a person in the middle. Mounted beside /studio/chat rather
# than replacing it: the one-shot route is live and metered, and both will run
# side by side until the frontend has moved over.
api_router.include_router(
    sessions.router, prefix="/studio/sessions", tags=["Design Sessions"]
)

# Built files. The studio is the only generator now, but the artifacts it
# produces are still reached through both link shapes — see app/api/v1/
# artifacts.py for why the /ofl/download one can never be withdrawn.
api_router.include_router(artifacts.router, prefix="/artifacts", tags=["Artifacts"])
api_router.include_router(artifacts.legacy_router, prefix="/ofl", tags=["Artifacts"])

# Which feature made which face. Separate from /artifacts because these routes
# read a sidecar and answer questions about it, rather than serving a file.
api_router.include_router(topology.router, prefix="/topology", tags=["Topology"])

# Click a face, change the feature that made it. Mounted under /studio/edit
# rather than beside /topology: reading geometry and changing a design are
# different acts, and only the second one is metered.
api_router.include_router(editing.router, prefix="/studio/edit", tags=["Editing"])

# The verification watchdog: engine status and robot-model runs. Assembly and
# drawing checks are mounted as their own apps at /verify and /drawing.
api_router.include_router(watchdog.router, prefix="/watchdog", tags=["Watchdog"])

# OrionFlow Inspect: first article inspection from a drawing (+ STEP, + PO).
# Every rule lives in the standalone `fai` package; this is the HTTP surface.
api_router.include_router(fai.router, prefix="/fai", tags=["Inspect (FAI)"])

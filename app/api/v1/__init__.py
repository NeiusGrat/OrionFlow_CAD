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
    jobs,
    studio,
    waitlist,
)

api_router = APIRouter(prefix="/api/v1")

# Mount sub-routers
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(designs.router, prefix="/designs", tags=["Designs"])
api_router.include_router(billing.router, prefix="/billing", tags=["Billing"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["Jobs"])
api_router.include_router(waitlist.router, prefix="/waitlist", tags=["Waitlist"])
api_router.include_router(agent.router, prefix="/agent", tags=["Agent"])
api_router.include_router(studio.router, prefix="/studio", tags=["Studio"])

# Built files. The studio is the only generator now, but the artifacts it
# produces are still reached through both link shapes — see app/api/v1/
# artifacts.py for why the /ofl/download one can never be withdrawn.
api_router.include_router(artifacts.router, prefix="/artifacts", tags=["Artifacts"])
api_router.include_router(artifacts.legacy_router, prefix="/ofl", tags=["Artifacts"])

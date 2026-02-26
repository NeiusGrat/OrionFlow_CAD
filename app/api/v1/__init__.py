"""
API v1 router aggregation.

All v1 endpoints are mounted under /api/v1/
"""

from fastapi import APIRouter

from app.api.v1 import auth, users, designs, billing, jobs, ofl

api_router = APIRouter(prefix="/api/v1")

# Mount sub-routers
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(designs.router, prefix="/designs", tags=["Designs"])
api_router.include_router(billing.router, prefix="/billing", tags=["Billing"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["Jobs"])
api_router.include_router(ofl.router, prefix="/ofl", tags=["OFL"])

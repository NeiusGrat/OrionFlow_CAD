"""Mount the standalone engines into the main FastAPI app.

    /verify/api/...    interface_check service (assembly, BOM, revisions, drawings, URDF drift)
    /drawing/api/...   drawcheck (incoming drawing checker)
    /review/api/...    OrionFlow Review (robot hardware review: model graph, checks, lenses)

Both accept the main app's own access tokens, so a user signed in to the
studio needs no second login. A missing optional dependency disables one
engine and is reported by ``/api/v1/watchdog/modules``; it never stops the
main app from starting.
"""
from __future__ import annotations

import os

import structlog

logger = structlog.get_logger(__name__)

#: engine name -> None when mounted, else the reason it is not
STATUS: dict[str, str | None] = {}


def _token_user(authorization: str) -> str:
    """User id from a main-app access token, or raise 401."""
    from fastapi import HTTPException

    from app.auth.jwt import verify_token

    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token", headers={"WWW-Authenticate": "Bearer"})
    payload = verify_token(authorization[7:].strip(), token_type="access")
    if payload is None or not payload.sub:
        raise HTTPException(401, "invalid or expired token", headers={"WWW-Authenticate": "Bearer"})
    return str(payload.sub)


def mount_engines(app) -> None:
    from app.config import settings

    # interface_check reads its config from the environment when its context is
    # first built, so the shared secret has to be in place before any request.
    os.environ.setdefault("IC_JWT_SECRET", settings.jwt_secret_key)
    os.environ.setdefault("IC_JWT_ALG", settings.jwt_algorithm)
    try:
        from interface_check.service.api import app as ic_app

        app.mount("/verify", ic_app, name="verify")
        STATUS["interface_check"] = None
    except Exception as e:  # noqa: BLE001
        STATUS["interface_check"] = f"{type(e).__name__}: {e}"
        logger.warning("watchdog_engine_unavailable", engine="interface_check", error=str(e))

    try:
        from fastapi import Header

        import review.api as rv

        def review_owner(authorization: str = Header(default="")) -> str:
            return _token_user(authorization)

        rv.app.dependency_overrides[rv.owner] = review_owner
        app.mount("/review", rv.app, name="review")
        STATUS["review"] = None
    except Exception as e:  # noqa: BLE001
        STATUS["review"] = f"{type(e).__name__}: {e}"
        logger.warning("watchdog_engine_unavailable", engine="review", error=str(e))

    try:
        from fastapi import Header

        import drawcheck.api as dc

        def drawcheck_owner(authorization: str = Header(default="")) -> str:
            return _token_user(authorization)

        # A separate app sharing drawcheck's routes, so the override lives here and the
        # standalone drawcheck app (python -m drawcheck serve) keeps its own auth.
        from fastapi import FastAPI

        sub = FastAPI(title="drawcheck (mounted)", version=dc.app.version)
        sub.include_router(dc.app.router)          # fresh routes, bound to sub's overrides
        sub.dependency_overrides[dc._auth] = drawcheck_owner
        app.mount("/drawing", sub, name="drawing")
        STATUS["drawcheck"] = None
    except Exception as e:  # noqa: BLE001
        STATUS["drawcheck"] = f"{type(e).__name__}: {e}"
        logger.warning("watchdog_engine_unavailable", engine="drawcheck", error=str(e))


def start_background() -> None:
    """Mounted sub-apps get no startup event, so the parent starts their loops."""
    import threading

    from app.watchdog.robot import interpreter

    # Finding a MuJoCo-capable interpreter imports build123d in a child (~10 s);
    # do it now so the first /watchdog/modules call does not wait for it.
    threading.Thread(target=interpreter, daemon=True, name="robot-interpreter-probe").start()
    if STATUS.get("interface_check") is None and "interface_check" in STATUS:
        try:
            from interface_check.service.api import _local_maintenance

            _local_maintenance()
        except Exception as e:  # noqa: BLE001
            logger.warning("watchdog_maintenance_not_started", error=str(e))

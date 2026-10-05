"""Who is calling, and on which plan.

The plan is resolved server-side (:mod:`.plans`: billing tables, then operator
overrides, then the default) — never taken from the token.

Accepts the main OrionFlow API's own access tokens (HS256, ``type: access``,
``sub`` = user id) signed with the shared secret ``IC_JWT_SECRET``, so a user
signed in to app.orionflow.in needs no second login. ``IC_DEV_TOKEN`` exists
for local development only.

There is no anonymous mode: with neither configured every call is refused,
so nobody unauthenticated can start a worker.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header, HTTPException

from .dispatch import context


@dataclass
class User:
    id: str
    plan: str
    admin: bool = False
    plan_source: str = "default"        # billing | operator | default


def _with_plan(uid: str, admin: bool) -> User:
    from .plans import resolve
    ctx = context()
    plan, source = resolve(ctx.store.engine, uid, ctx.cfg.default_plan)
    return User(uid, plan, admin, source)


def current_user(authorization: str = Header(default="")) -> User:
    cfg = context().cfg
    if not (cfg.jwt_secret or cfg.dev_token):
        raise HTTPException(503, "authentication is not configured (set IC_JWT_SECRET)")
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token", headers={"WWW-Authenticate": "Bearer"})
    token = authorization[7:].strip()
    if cfg.dev_token and token == cfg.dev_token:
        return _with_plan("dev", "dev" in cfg.admin_users)
    if not cfg.jwt_secret:
        raise HTTPException(401, "invalid token")
    import jwt
    try:
        claims = jwt.decode(token, cfg.jwt_secret, algorithms=[cfg.jwt_alg])
    except jwt.PyJWTError:
        raise HTTPException(401, "invalid or expired token", headers={"WWW-Authenticate": "Bearer"}) from None
    if claims.get("type", "access") != "access" or not claims.get("sub"):
        raise HTTPException(401, "not an access token")
    uid = str(claims["sub"])
    return _with_plan(uid, uid in cfg.admin_users or claims.get("role") == "admin")

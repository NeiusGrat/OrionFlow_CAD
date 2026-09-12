"""Per-worker isolation primitives (R5).

Model-generated code must never run with network access, an unbounded
memory budget, or in the harness's own process. These three functions are
called once, at worker startup, inside the child process -- never in the
parent.

Platform note: `resource.RLIMIT_AS` (hard memory cap) and network
namespaces are POSIX/Linux facilities. This repo's dev machine is Windows,
where `resource` does not exist and there is no unprivileged namespace
equivalent reachable from Python. `apply_memory_limit` degrades to a no-op
with a one-time warning on platforms without `resource`; the socket-level
network block in `block_network` is portable and enforced everywhere,
because it patches the `socket` module itself rather than relying on OS
namespaces. Deploy targets (Docker/Modal) are Linux, where the memory cap
is real.
"""

from __future__ import annotations

import socket
import warnings

try:
    import resource  # POSIX only
except ImportError:  # Windows
    resource = None  # type: ignore[assignment]

_network_blocked = False
_memory_limited = False


class NetworkAccessDisabled(PermissionError):
    pass


def block_network() -> None:
    """Monkeypatch socket so any connection attempt raises.

    Covers `socket`, and therefore anything built on it (urllib,
    http.client, requests, most CAD-kernel telemetry hooks) -- without
    needing root or a Linux network namespace.
    """

    global _network_blocked
    if _network_blocked:
        return

    def _deny(*_args, **_kwargs):
        raise NetworkAccessDisabled("network access disabled in harness sandbox")

    socket.socket.connect = _deny  # type: ignore[method-assign]
    socket.socket.connect_ex = _deny  # type: ignore[method-assign]
    socket.create_connection = _deny  # type: ignore[assignment]
    _network_blocked = True


def apply_memory_limit(memory_mb: int) -> bool:
    """Best-effort RLIMIT_AS cap. Returns True if actually applied."""

    global _memory_limited
    if resource is None:
        warnings.warn(
            "apply_memory_limit is a no-op on this platform (no `resource` "
            "module); memory caps are only enforced on POSIX deploy targets.",
            stacklevel=2,
        )
        return False
    limit_bytes = memory_mb * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))
    _memory_limited = True
    return True


MAX_CAPTURED_OUTPUT = 256 * 1024  # 256 kB, per §6.1


def truncate_output(text: str) -> str:
    if len(text) <= MAX_CAPTURED_OUTPUT:
        return text
    return text[:MAX_CAPTURED_OUTPUT] + "\n...[truncated]..."

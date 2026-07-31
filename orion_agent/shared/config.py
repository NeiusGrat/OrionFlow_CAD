"""Central typed configuration for the OrionFlow agent harness.

Deliberately stdlib-only (dataclasses + a tiny ``.env`` reader) so the exact
same module imports cleanly inside FreeCAD's embedded Python — which may not
ship pydantic — and inside the modern harness interpreter.

All knobs are read from the environment (``.env`` at repo root is auto-loaded
once). Every value has a safe default so missing config never crashes import.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

# --------------------------------------------------------------------------- #
# .env loading (no python-dotenv dependency)
# --------------------------------------------------------------------------- #

_ENV_LOADED = False


def _find_repo_root() -> Path:
    here = Path(__file__).resolve()
    # Prefer the directory that actually holds the .env / .git marker so a
    # nested package pyproject.toml never shadows the real repo root.
    for parent in here.parents:
        if (parent / ".env").exists() or (parent / ".git").exists():
            return parent
    return here.parents[2]


def _load_dotenv() -> None:
    """Populate ``os.environ`` from the repo-root ``.env`` once, non-destructively."""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True
    env_path = _find_repo_root() / ".env"
    if not env_path.exists():
        return
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            # Skip malformed keys (e.g. a stray "API Key=..." with a space).
            if not key or " " in key:
                continue
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)
    except OSError:
        pass


def _env(name: str, default: str = "") -> str:
    _load_dotenv()
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------- #
# Config model
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class LLMConfig:
    """LLM backend selection. The provider is a config value, not architecture."""

    provider: str = "vllm"
    #: The BASE adapter. Both adapters are served from one endpoint; the
    #: fine-tuned ``orionflow`` is selected per-call for geometry, because it
    #: answers every input with a Blueprint and so cannot carry a conversation
    #: or a tool loop.
    model: str = "orionflow-base"
    #: No default, and deliberately not localhost — see ``get_config``. One
    #: remotely served endpoint backs the studio and the desktop copilot, and
    #: an unset value fails loudly rather than pointing a deployed container at
    #: itself.
    base_url: str = ""
    api_key: str = ""
    # Blueprints are long; a smaller budget truncates them mid-JSON.
    max_tokens: int = 8192
    temperature: float = 0.2
    # Reasoning completions can run long; keep the read timeout generous.
    request_timeout: float = 300.0
    # Text-only; vision requests degrade to a textual description channel
    # until a VL model is configured here.
    supports_vision: bool = False
    supports_tools: bool = True


@dataclass(frozen=True)
class BridgeConfig:
    """Localhost bridge between the addon (server) and the harness (client)."""

    host: str = "127.0.0.1"
    port: int = 8765
    allow_list: tuple[str, ...] = ("127.0.0.1",)
    request_timeout: float = 120.0
    connect_retries: int = 3


@dataclass(frozen=True)
class HarnessConfig:
    """The harness HTTP service the chat UI talks to."""

    host: str = "127.0.0.1"
    port: int = 8770
    max_agent_steps: int = 12
    repair_budget: int = 3     # guided repair attempts per turn (see agent/repair.py)


@dataclass(frozen=True)
class SandboxConfig:
    """Resource caps for isolated code execution."""

    backend: str = "subprocess"  # "subprocess" | "docker" | "nsjail"
    timeout_seconds: int = 30  # build123d/OCP cold-start alone is ~8s
    memory_mb: int = 1024
    scratch_dir: str = "outputs/sandbox"
    allow_network: bool = False


@dataclass(frozen=True)
class OrionConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    bridge: BridgeConfig = field(default_factory=BridgeConfig)
    harness: HarnessConfig = field(default_factory=HarnessConfig)
    sandbox: SandboxConfig = field(default_factory=SandboxConfig)
    trajectory_dir: str = "data/trajectories"
    repo_root: str = field(default_factory=lambda: str(_find_repo_root()))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Never serialise the secret.
        d["llm"]["api_key"] = "***" if self.llm.api_key else ""
        return d


def get_config() -> OrionConfig:
    """Build the config snapshot from the current environment."""
    _load_dotenv()
    # OrionFlow's own weights are the default everywhere. The desktop copilot
    # ran on a third-party reasoning API while the studio ran on the fine-tune,
    # which meant two products with different engineering intelligence and
    # customer designs leaving for an outside service. One model family, one
    # endpoint, everywhere.
    #
    # "One model" is two adapters on that endpoint, not one set of weights:
    # ``orionflow`` is trained to answer every input with a Blueprint, so it
    # cannot hold a conversation or drive a tool loop. ``orionflow-base`` is the
    # untouched base served alongside it for exactly that. The agent loop needs
    # tool calling, so it takes the base; geometry generation takes the adapter.
    llm = LLMConfig(
        provider=_env("ORION_LLM_PROVIDER", "vllm"),
        model=_env("ORION_LLM_MODEL", "orionflow-base"),
        # Provider-neutral names win; the K2THINK_* names stay as fallbacks so
        # existing .env files keep working. Pointing the agent at a self-hosted
        # endpoint should not require setting a variable named after the vendor
        # being replaced.
        # No default endpoint, and deliberately not localhost. One remotely
        # served model backs both the studio and the desktop copilot, so the
        # address is deployment configuration and belongs in the environment —
        # ORION_LLM_BASE_URL, set in the Modal secret for production.
        #
        # A localhost default is worse than none. It turns "the endpoint was
        # never configured" into a connection refused against the operator's own
        # machine, or on a box that happens to be serving something on that
        # port, into answers from the wrong model with nothing to indicate it.
        # Unset now fails loudly and says which variable to set.
        #
        # For local development, set it explicitly:
        #     ORION_LLM_BASE_URL=http://127.0.0.1:8100/v1
        base_url=_env("ORION_LLM_BASE_URL", _env("K2THINK_BASE_URL", "")),
        api_key=_env("ORION_LLM_API_KEY", _env("K2THINK_API_KEY", "")),
        max_tokens=_env_int("ORION_LLM_MAX_TOKENS", 8192),
        temperature=_env_float("ORION_LLM_TEMPERATURE", 0.2),
        request_timeout=_env_float("ORION_LLM_TIMEOUT", 300.0),
        supports_vision=_env("ORION_LLM_VISION", "false").lower() == "true",
    )
    bridge = BridgeConfig(
        host=_env("ORION_BRIDGE_HOST", "127.0.0.1"),
        port=_env_int("ORION_BRIDGE_PORT", 8765),
        request_timeout=_env_float("ORION_BRIDGE_TIMEOUT", 120.0),
    )
    harness = HarnessConfig(
        host=_env("ORION_HARNESS_HOST", "127.0.0.1"),
        port=_env_int("ORION_HARNESS_PORT", 8770),
        max_agent_steps=_env_int("ORION_MAX_AGENT_STEPS", 12),
        repair_budget=_env_int("ORION_REPAIR_BUDGET", 3),
    )
    sandbox = SandboxConfig(
        backend=_env("ORION_SANDBOX_BACKEND", "subprocess"),
        timeout_seconds=_env_int("ORION_SANDBOX_TIMEOUT_SECONDS", 20),
        memory_mb=_env_int("ORION_SANDBOX_MEMORY_MB", 1024),
    )
    return OrionConfig(
        llm=llm,
        bridge=bridge,
        harness=harness,
        sandbox=sandbox,
        trajectory_dir=_env("ORION_TRAJECTORY_DIR", "data/trajectories"),
    )


# Convenience singleton for callers that just want the current config.
_CONFIG: Optional[OrionConfig] = None


def config() -> OrionConfig:
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = get_config()
    return _CONFIG

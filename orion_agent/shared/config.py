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

    provider: str = "k2think"
    model: str = "MBZUAI-IFM/K2-Think-v2"
    # k2v2 think official developer API — OpenAI-compatible chat completions.
    base_url: str = "https://api.k2think.ai/v1/chat/completions"
    api_key: str = ""
    # K2-Think emits a long inline <think> block before the answer/tool-call, so
    # it needs generous headroom or the trailing tool call gets truncated.
    max_tokens: int = 8192
    temperature: float = 0.2
    # K2-Think reasoning completions can run long; keep the read timeout generous.
    request_timeout: float = 300.0
    # K2-Think is text-only; vision requests degrade to a textual description
    # channel until a VL model is configured here.
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
    llm = LLMConfig(
        provider=_env("ORION_LLM_PROVIDER", "k2think"),
        model=_env("ORION_LLM_MODEL", "MBZUAI-IFM/K2-Think-v2"),
        base_url=_env("K2THINK_BASE_URL", "https://api.k2think.ai/v1/chat/completions"),
        api_key=_env("K2THINK_API_KEY", ""),
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

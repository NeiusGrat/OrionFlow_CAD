"""Name -> callable lookup for verifiers (§7.1).

A verifier is registered exactly once under its name (R1). Its version
string is part of the cache key (R4); bumping behaviour without bumping
the version is a bug (AGENTS.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .contracts import GateResult, Metric


@dataclass(frozen=True)
class VerifierEntry:
    name: str
    version: str
    fn: Callable[..., GateResult | Metric]


_VERIFIERS: dict[str, VerifierEntry] = {}


class DuplicateVerifierError(Exception):
    pass


class UnknownVerifierError(Exception):
    pass


def register_verifier(name: str, version: str):
    """Decorator: register fn under `name`, versioned.

    Re-registering the same name is a DuplicateVerifierError unless the
    version string also changes -- re-importing a module at test time with
    an identical (name, version) is a no-op, not an error.
    """

    def deco(fn):
        existing = _VERIFIERS.get(name)
        if existing is not None and existing.version != version:
            raise DuplicateVerifierError(
                f"verifier '{name}' already registered at version "
                f"{existing.version!r}; refusing silent version bump to "
                f"{version!r} via re-registration"
            )
        _VERIFIERS[name] = VerifierEntry(name=name, version=version, fn=fn)
        return fn

    return deco


def get_verifier(name: str) -> VerifierEntry:
    try:
        return _VERIFIERS[name]
    except KeyError as e:
        raise UnknownVerifierError(f"no verifier registered under {name!r}") from e


def verifier_version(name: str) -> str:
    return get_verifier(name).version


def all_verifiers() -> dict[str, VerifierEntry]:
    return dict(_VERIFIERS)

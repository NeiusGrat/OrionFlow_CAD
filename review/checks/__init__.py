"""OrionFlow Review checks. Each module registers its checks with :func:`base.check`."""
from .base import REGISTRY, CheckConfig, Finding, run_checks  # noqa: F401

_MODULES = ("structure", "interfaces", "clearance")


def load_all() -> None:
    import importlib
    for m in _MODULES:
        importlib.import_module(f"{__name__}.{m}")

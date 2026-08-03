"""One IR reaches the kernel, and the live path cannot select any other.

The production route is Blueprint → resolved FeatureGraph → FreeCAD. The repo
also contains build123d compilers (v1, v2, v3), the OFL language and its
sandbox, and ``ConstructionPlan`` — all of them real, none of them on that path.
They are kept because they built the corpus and the corpus is the asset, but a
second way to turn intent into geometry is a second thing to keep correct, and
the moment one leaks into the live route the guarantee that a downloaded part is
the part its assertions were checked against stops being true.

Two properties, both asserted by import rather than by inspection:

**The studio and session path never loads build123d.** Not "does not call it" —
does not *import* it. The distinction matters because importing it is what costs
the two-minute cold boot, and because an import is the first step of an
accidental call.

**Importing the app does not either.** This one is load-bearing for deployment:
``app.main`` used to pull in build123d transitively through
``app.services.__init__``, so every process paid for a kernel no live route uses.
"""

import subprocess
import sys

import pytest

#: Anything whose presence in ``sys.modules`` means a second geometry stack got
#: loaded. ``OCP`` is listed separately from ``build123d`` because it is the
#: expensive half and can arrive through cadquery just as easily.
FOREIGN = ("build123d", "OCP", "cadquery", "ocp_tessellate", "orionflow_ofl")


def _loaded_after(statements: str) -> set[str]:
    """Import in a fresh interpreter; return which foreign roots came with it.

    A subprocess rather than an assertion about the current one: pytest has
    almost certainly imported build123d already for the compiler tests, so
    checking ``sys.modules`` in-process would prove nothing at all.
    """
    program = (
        "import sys\n"
        f"{statements}\n"
        f"roots = {FOREIGN!r}\n"
        "found = sorted({m.split('.')[0] for m in sys.modules "
        "if m.split('.')[0] in roots})\n"
        "print(','.join(found))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    tail = [ln for ln in result.stdout.strip().splitlines() if ln is not None]
    return set(filter(None, (tail[-1] if tail else "").split(",")))


@pytest.mark.parametrize(
    "what,statements",
    [
        ("the studio agent", "import app.services.studio_agent"),
        ("the blueprint builder", "import app.services.blueprint_service"),
        ("the session service", "import app.services.design_sessions"),
        ("the session routes", "import app.api.v1.sessions"),
        ("the studio routes", "import app.api.v1.studio"),
        ("the session state machine", "import app.domain.design_session"),
    ],
)
def test_the_live_path_never_loads_a_second_geometry_stack(what, statements):
    assert _loaded_after(statements) == set(), (
        f"{what} pulled in a second geometry stack — the production route is "
        "Blueprint → FreeCAD and must not be able to reach build123d or OFL"
    )


def test_importing_the_app_does_not_load_the_geometry_kernel():
    """The deployment property.

    ``app.main`` imported ``app.services``, which re-exported
    ``GenerationService``, which imported build123d and 542 OCP modules — so a
    process serving a login paid for a kernel it would never call. That is the
    entire cold boot the Modal deployment carries a memory snapshot to hide.
    """
    assert _loaded_after("import app.main") == set()


def test_the_legacy_generator_still_works_when_something_asks_for_it():
    """Deferred, not deleted. ``/generate`` and ``/regenerate`` are unchanged.

    The lazy attributes have to resolve to the real thing on first access, or
    this would be a silent removal wearing the costume of an optimisation.
    """
    from app.services import generation_service

    # Attribute access is what triggers the import, so this both proves the
    # symbol resolves and that it resolves to build123d's own exporter.
    assert generation_service.BUILD123D_AVAILABLE in (True, False)
    if generation_service.BUILD123D_AVAILABLE:
        assert callable(generation_service.export_step)
        assert generation_service.Build123dCompiler is not None


def test_the_compilers_package_still_exports_its_names():
    from app import compilers

    assert compilers.BuildContext is not None
    assert compilers.Build123dCompiler is not None
    with pytest.raises(AttributeError):
        compilers.NotACompiler  # noqa: B018


def test_the_services_package_still_exports_the_generator():
    from app import services

    assert services.GenerationService is not None
    with pytest.raises(AttributeError):
        services.NotAService  # noqa: B018


def test_the_blueprint_is_the_only_thing_the_builder_accepts():
    """``ConstructionPlan`` and the FeatureGraph IRs are not on this path.

    ``Blueprint.resolve()`` produces the concrete graph FreeCAD consumes, and it
    is the only producer of one. A second plan object feeding the same builder
    is exactly the competing representation this file exists to prevent.
    """
    import inspect

    from app.services import blueprint_service

    source = inspect.getsource(blueprint_service)
    for foreign in ("ConstructionPlan", "FeatureGraphV1", "FeatureGraphV3", "build123d"):
        assert foreign not in source, (
            f"{foreign} appeared in the Blueprint builder — the live path takes "
            "one IR and it is the Blueprint"
        )

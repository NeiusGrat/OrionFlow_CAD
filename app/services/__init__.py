"""
Services package for OrionFlow CAD.

``GenerationService`` is resolved on demand rather than imported here. It is the
legacy build123d generator, and re-exporting it eagerly meant that *any* import
of ``app.services`` — the studio agent, the session service, the artifact
helpers, all of which have nothing to do with build123d — dragged the whole
geometry kernel in behind it.
"""

__all__ = ["GenerationService"]


def __getattr__(name: str):
    if name == "GenerationService":
        from app.services.generation_service import GenerationService

        return GenerationService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

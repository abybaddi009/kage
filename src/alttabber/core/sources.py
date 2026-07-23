"""Plugin interface for launcher result sources.

Third-party packages can register entry points in the ``alttabber.sources`` group::

    [project.entry-points."alttabber.sources"]
    my-source = "my_pkg.alttabber_source:MySource"

Each entry point resolves to a callable returning an object implementing the
:class:`ResultSource` protocol (a ``search(query)`` method returning a list
of :class:`~alttabber.core.matcher.Result`). Alt-Tabber loads all sources at palette
build time and merges their results into the launcher.
"""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Protocol, runtime_checkable

from .matcher import Result


@runtime_checkable
class ResultSource(Protocol):
    """A plugin that contributes results to the launcher palette."""

    def search(self, query: str) -> list[Result]:
        """Return results matching ``query`` (may be empty)."""
        ...


def load_sources() -> list[ResultSource]:
    """Discover and instantiate all registered ``alttabber.sources`` plugins.

    A broken plugin is skipped (logged to stderr) so one bad plugin can't
    take down the launcher.
    """
    sources: list[ResultSource] = []
    try:
        eps = entry_points(group="alttabber.sources")
    except TypeError:  # py<3.10 select interface
        try:
            eps = entry_points().get("alttabber.sources", [])
        except Exception:
            eps = []
    except Exception:
        eps = []
    for ep in eps:
        try:
            factory = ep.load()
            obj = factory() if callable(factory) else factory
            if isinstance(obj, ResultSource):
                sources.append(obj)
        except Exception as exc:  # pragma: no cover - plugin errors
            import sys

            print(f"alttabber: skipping source {ep.name!r}: {exc}", file=sys.stderr)
    return sources

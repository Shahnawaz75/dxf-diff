"""Dataclasses that describe the differences between two DXF drawings."""

from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field, fields
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Union

from ._version import __version__

REPORT_FORMAT, REPORT_FORMAT_VERSION = "dxf-diff-report", 1


class DxfDiffError(Exception):
    """A problem the user can fix, e.g. a missing, unreadable or DWG input file."""


class ChangeKind(str, Enum):
    """How an entity, layer or block differs between the OLD and the NEW drawing."""

    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
    UNCHANGED = "unchanged"

    def __str__(self) -> str:
        return self.value

    def __format__(self, spec: str) -> str:
        return format(self.value, spec)


KIND_ORDER = {ChangeKind.ADDED: 0, ChangeKind.REMOVED: 1, ChangeKind.MODIFIED: 2, ChangeKind.UNCHANGED: 3}


class _Record:
    """Mixin giving the change dataclasses a ``to_dict()`` (ezdxf entity references are left out)."""

    def to_dict(self) -> Dict[str, Any]:
        return {f.name: to_jsonable(getattr(self, f.name)) for f in fields(self) if f.repr}  # type: ignore[arg-type]


def to_jsonable(value: Any) -> Any:
    """Convert records and property values (point tuples, dicts, enums, numpy scalars) to JSON types."""
    if isinstance(value, _Record):
        return value.to_dict()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    if value is None or isinstance(value, (bool, int, str)):
        return value
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return 0.0 if number == 0 else number


@dataclass(frozen=True)
class PropertyChange(_Record):
    """One property whose value differs: ``name`` went from ``old`` to ``new``."""

    name: str
    old: Any
    new: Any


@dataclass
class EntityChange(_Record):
    """The comparison result for one entity of OLD and/or NEW.

    ``old_entity`` and ``new_entity`` are the underlying ezdxf entities, or ``None``
    on the side where the entity does not exist. ``matched_by`` tells how the pair
    was found: ``"handle"``, ``"geometry"`` or ``"similarity"``.
    """

    kind: ChangeKind
    dxftype: str
    layer: str
    space: str = "Model"
    old_handle: Optional[str] = None
    new_handle: Optional[str] = None
    description: str = ""
    changes: List[PropertyChange] = field(default_factory=list)
    matched_by: Optional[str] = None
    old_entity: Any = field(default=None, repr=False, compare=False)
    new_entity: Any = field(default=None, repr=False, compare=False)

    @property
    def handle(self) -> str:
        """The NEW handle if the entity exists in NEW, otherwise the OLD handle."""
        return self.new_handle or self.old_handle or ""


@dataclass
class LayerChange(_Record):
    """A layer that was added, removed or whose table properties changed."""

    kind: ChangeKind
    name: str
    description: str = ""
    changes: List[PropertyChange] = field(default_factory=list)


@dataclass
class BlockChange(_Record):
    """A named block definition that was added, removed or whose content changed."""

    kind: ChangeKind
    name: str
    description: str = ""
    changes: List[PropertyChange] = field(default_factory=list)
    details: List[str] = field(default_factory=list)  # descriptions of the changed block entities


def _as_set(value: Any, convert: Callable[[Any], Any]) -> Optional[set]:
    if value is None:
        return None
    return {convert(v) for v in ([value] if isinstance(value, (str, Enum)) else value)}


def _count(items: Iterable[Any], kinds: Iterable[ChangeKind]) -> Dict[str, int]:
    counts = {k.value: 0 for k in kinds}
    for item in items:
        counts[item.kind.value] += 1
    return counts


@dataclass
class DiffResult:
    """Everything that differs between two drawings.

    Iterating over a result yields the entity differences (added, removed and
    modified entities). Unchanged entities stay available in :attr:`entities`.
    """

    old_path: str
    new_path: str
    entities: List[EntityChange] = field(default_factory=list)
    layers: List[LayerChange] = field(default_factory=list)
    blocks: List[BlockChange] = field(default_factory=list)
    options: Dict[str, Any] = field(default_factory=dict)
    old_doc: Any = field(default=None, repr=False, compare=False)
    new_doc: Any = field(default=None, repr=False, compare=False)

    def __iter__(self) -> Iterator[EntityChange]:
        return iter(self.changes)

    @property
    def changes(self) -> List[EntityChange]:
        """Added, removed and modified entities (everything except unchanged)."""
        return [e for e in self.entities if e.kind is not ChangeKind.UNCHANGED]

    @property
    def added(self) -> List[EntityChange]:
        return self.filter(kind=ChangeKind.ADDED)

    @property
    def removed(self) -> List[EntityChange]:
        return self.filter(kind=ChangeKind.REMOVED)

    @property
    def modified(self) -> List[EntityChange]:
        return self.filter(kind=ChangeKind.MODIFIED)

    @property
    def unchanged(self) -> List[EntityChange]:
        return self.filter(kind=ChangeKind.UNCHANGED)

    @property
    def has_changes(self) -> bool:
        """True if any entity, layer or block definition differs."""
        return bool(self.layers or self.blocks or self.changes)

    def filter(
        self,
        kind: Union[None, str, ChangeKind, Iterable[Union[str, ChangeKind]]] = None,
        dxftype: Union[None, str, Iterable[str]] = None,
        layer: Optional[str] = None,
        space: Optional[str] = None,
    ) -> List[EntityChange]:
        """Entity changes matching all given criteria.

        ``kind`` and ``dxftype`` accept one value or several; ``layer`` is a
        case-insensitive wildcard pattern such as ``"NOZ*"``. Unchanged entities
        are only returned when asked for explicitly with ``kind="unchanged"``.
        """
        kinds = _as_set(kind, lambda k: ChangeKind(str(k).lower()))
        types = _as_set(dxftype, lambda t: str(t).upper())
        return [
            c
            for c in (self.entities if kinds else self.changes)
            if (kinds is None or c.kind in kinds)
            and (types is None or c.dxftype.upper() in types)
            and (layer is None or fnmatch.fnmatchcase(c.layer.upper(), layer.upper()))
            and (space is None or c.space.upper() == space.upper())
        ]

    def summary(self) -> Dict[str, Dict[str, int]]:
        """Counts per kind for entities, layers and blocks."""
        tables = (ChangeKind.ADDED, ChangeKind.REMOVED, ChangeKind.MODIFIED)
        return {
            "entities": _count(self.entities, ChangeKind),
            "layers": _count(self.layers, tables),
            "blocks": _count(self.blocks, tables),
        }

    def to_dict(self, include_unchanged: bool = False) -> Dict[str, Any]:
        """A JSON-serializable dict (the format written by ``dxf-diff --json``)."""
        return {
            "format": REPORT_FORMAT,
            "format_version": REPORT_FORMAT_VERSION,
            "tool": {"name": "dxf-diff", "version": __version__},
            "old": {"path": self.old_path, "dxfversion": getattr(self.old_doc, "dxfversion", None)},
            "new": {"path": self.new_path, "dxfversion": getattr(self.new_doc, "dxfversion", None)},
            "options": to_jsonable(self.options),
            "has_changes": self.has_changes,
            "summary": self.summary(),
            "entities": to_jsonable(self.entities if include_unchanged else self.changes),
            "layers": to_jsonable(self.layers),
            "blocks": to_jsonable(self.blocks),
        }

    def to_json(self, path: Union[None, str, Path] = None, *, indent: int = 2, include_unchanged: bool = False) -> str:
        """Serialize to JSON; also write it to ``path`` when given."""
        text = json.dumps(self.to_dict(include_unchanged), indent=indent, ensure_ascii=False)
        if path is not None:
            with open(path, "w", encoding="utf-8", newline="\n") as fp:
                fp.write(text + "\n")
        return text

"""Load drawings, pair up their entities and classify the differences.

Matching runs in passes, each one only looking at entities not paired yet:

1. **handle** - same handle and type (skipped when handles look unrelated, e.g.
   in a re-exported file),
2. **geometry** - same geometric fingerprint (type + layer + rounded geometry),
3. **similarity** - only when handles were not trusted: one unique leftover pair
   sharing an anchor such as the insert point of a TEXT or the block name +
   insert point of an INSERT.

Paired entities are *unchanged* or *modified*; the rest are *removed* or *added*.
"""

from __future__ import annotations

import fnmatch
import logging
import math
import os
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from typing import Any, Callable, Dict, FrozenSet, Hashable, Iterator, List, Optional, Sequence, Tuple, Union

import ezdxf
from ezdxf import recover
from ezdxf.document import Drawing

from .describe import describe_layer, describe_modification, fmt_color, summarize
from .extract import (
    CASE_INSENSITIVE,
    PROP_ALIASES,
    base_point,
    common_props,
    freeze,
    geometry_props,
    layer_props,
    named_blocks,
    similarity_keys,
    values_differ,
)
from .model import (
    KIND_ORDER,
    BlockChange,
    ChangeKind,
    DiffResult,
    DxfDiffError,
    EntityChange,
    LayerChange,
    PropertyChange,
)

Source = Union[str, "os.PathLike[str]", Drawing]
MATCH_MODES = ("auto", "handle", "geometry")
_log = logging.getLogger("dxf_diff")
_DWG_MAGIC = re.compile(rb"^AC(\d{4}|[12]\.\d\d)")


def _as_tuple(value: Any) -> Tuple[str, ...]:
    if not value:
        return ()
    return (value,) if isinstance(value, str) else tuple(str(v) for v in value)


@dataclass
class CompareOptions:
    """Settings that control how two drawings are compared (see :func:`compare`)."""

    tolerance: float = 1e-6
    layers: Sequence[str] = ()
    ignore_layers: Sequence[str] = ()
    ignore_props: Sequence[str] = ()
    layouts: bool = False
    match: str = "auto"

    def __post_init__(self) -> None:
        if not (math.isfinite(self.tolerance) and self.tolerance >= 0):
            raise ValueError("tolerance must be a finite number >= 0")
        if self.match not in MATCH_MODES:
            raise ValueError(f"match must be one of: {', '.join(MATCH_MODES)}")
        self.layers, self.ignore_layers = _as_tuple(self.layers), _as_tuple(self.ignore_layers)
        names = [n.strip().lower() for item in _as_tuple(self.ignore_props) for n in item.split(",")]
        self.ignore_props = tuple(n for n in names if n)

    @property
    def ignored(self) -> FrozenSet[str]:
        """Property names excluded from the comparison, with aliases expanded."""
        return frozenset(name for n in self.ignore_props for name in PROP_ALIASES.get(n, (n,)))

    @property
    def ndigits(self) -> int:
        """Decimal places used to round values in geometric fingerprints."""
        return 10 if self.tolerance <= 0 else max(0, min(10, round(-math.log10(self.tolerance))))

    def layer_selected(self, name: str) -> bool:
        """True if entities on layer ``name`` take part in the comparison."""
        upper = str(name).upper()
        if self.layers and not any(fnmatch.fnmatchcase(upper, p.upper()) for p in self.layers):
            return False
        return not any(fnmatch.fnmatchcase(upper, p.upper()) for p in self.ignore_layers)


def load_drawing(source: Source) -> Tuple[Drawing, str]:
    """Return ``(drawing, name)`` for a DXF file path or an already loaded drawing."""
    if isinstance(source, Drawing):
        return source, str(source.filename or "<drawing>")
    path = os.fspath(source)
    if not os.path.isfile(path):
        raise DxfDiffError(f"no such file: {path}")
    with open(path, "rb") as fp:
        if _DWG_MAGIC.match(fp.read(16)):
            raise DxfDiffError(
                f"{path} is a DWG file; dxf-diff reads DXF only. "
                "Convert it to DXF first, e.g. with the free ODA File Converter or LibreCAD."
            )
    try:
        return ezdxf.readfile(path), path
    except ezdxf.DXFStructureError:
        pass
    except Exception as exc:
        raise DxfDiffError(f"cannot read {path}: {exc}") from exc
    try:  # damaged file: let ezdxf repair what it can
        doc, auditor = recover.readfile(path)
    except Exception as exc:
        raise DxfDiffError(f"cannot read {path}: {exc}") from exc
    _log.warning("dxf-diff: warning: %s is damaged; comparing what could be recovered", path)
    return doc, path


@dataclass
class _Item:
    """An entity prepared for matching."""

    entity: Any
    space: str
    handle: str
    dxftype: str
    layer: str
    geom: Dict[str, Any]  # type specific properties
    common: Dict[str, Any]  # layer, color, linetype ...
    fingerprint: Hashable
    similar: List[Optional[Hashable]]


def _make_item(entity: Any, space: str, ignored: FrozenSet[str], ndigits: int) -> _Item:
    dxftype, layer = entity.dxftype(), str(entity.dxf.get("layer", "0"))
    geom = {k: v for k, v in geometry_props(entity).items() if k not in ignored}
    common = {k: v for k, v in {"layer": layer, **common_props(entity)}.items() if k not in ignored}
    fingerprint = (dxftype, "" if "layer" in ignored else layer.upper(), freeze(geom, ndigits))
    handle, similar = str(entity.dxf.get("handle", "")), similarity_keys(dxftype, geom, ndigits)
    return _Item(entity, space, handle, dxftype, layer, geom, common, fingerprint, similar)


def _spaces(doc: Drawing, layouts: bool) -> Iterator[Tuple[str, Any]]:
    yield "Model", doc.modelspace()
    for name in doc.layouts.names_in_taborder() if layouts else ():
        if name.upper() != "MODEL":
            yield name, doc.layouts.get(name)


def _collect(doc: Drawing, opts: CompareOptions) -> List[_Item]:
    ignored, ndigits = opts.ignored, opts.ndigits
    return [
        _make_item(entity, space, ignored, ndigits)
        for space, layout in _spaces(doc, opts.layouts)
        for entity in layout
        if opts.layer_selected(entity.dxf.get("layer", "0"))
    ]


def same_lineage(a: Drawing, b: Drawing) -> bool:
    """True if both drawings carry the same ``$FINGERPRINTGUID`` (same origin file)."""
    guid = a.header.get("$FINGERPRINTGUID")
    return bool(guid) and guid == b.header.get("$FINGERPRINTGUID")


def _trust_handles(old: List[_Item], new: List[_Item], match: str, lineage: bool) -> bool:
    """Decide whether handles identify the same entity in both drawings."""
    if match != "auto":
        return match == "handle"
    if lineage:
        return True
    by_handle = {(it.space, it.handle): it for it in new}
    common = same = 0
    for it in old:
        other = by_handle.get((it.space, it.handle))
        if other is not None and other.dxftype == it.dxftype:
            common += 1
            same += other.fingerprint == it.fingerprint
    # Unrelated files reuse the same small handle numbers for different entities.
    return common > 0 and 2 * same >= common


def diff_props(old: Dict[str, Any], new: Dict[str, Any], tol: float) -> List[PropertyChange]:
    """All properties whose values differ by more than ``tol``."""
    keys = list(old) + [k for k in new if k not in old]
    return [
        PropertyChange(k, old.get(k), new.get(k))
        for k in keys
        if values_differ(old.get(k), new.get(k), tol, k in CASE_INSENSITIVE)
    ]


def _compare_pair(o: _Item, n: _Item, how: str, tol: float) -> EntityChange:
    changes = diff_props({**o.geom, **o.common}, {**n.geom, **n.common}, tol)
    kind = ChangeKind.MODIFIED if changes else ChangeKind.UNCHANGED
    description = describe_modification(n.dxftype, n.geom, changes, tol) if changes else ""
    return EntityChange(
        kind, n.dxftype, n.layer, n.space, o.handle, n.handle, description, changes, how, o.entity, n.entity
    )


def _single(kind: ChangeKind, it: _Item) -> EntityChange:
    change = EntityChange(kind, it.dxftype, it.layer, it.space, description=summarize(it.dxftype, it.geom))
    if kind is ChangeKind.REMOVED:
        change.old_handle, change.old_entity = it.handle, it.entity
    else:
        change.new_handle, change.new_entity = it.handle, it.entity
    return change


def _sort_key(c: EntityChange) -> Tuple[Any, ...]:
    handle = int(c.handle, 16) if re.fullmatch("[0-9A-Fa-f]+", c.handle) else 0
    return (KIND_ORDER[c.kind], c.space != "Model", c.space.upper(), c.dxftype, c.layer.upper(), handle)


def _similarity_key(level: int) -> Callable[[_Item], Optional[Hashable]]:
    def key(it: _Item) -> Optional[Hashable]:
        if level < len(it.similar) and it.similar[level] is not None:
            return (it.space, it.dxftype, it.layer.upper(), level, it.similar[level])
        return None

    return key


def match_entities(
    old: List[_Item], new: List[_Item], opts: CompareOptions, lineage: bool = False
) -> List[EntityChange]:
    """Pair OLD and NEW items and return one :class:`EntityChange` per entity (pair)."""
    pairs: List[Tuple[int, int, str]] = []
    left_old, left_new = set(range(len(old))), set(range(len(new)))

    def pair_by(key: Callable[[_Item], Optional[Hashable]], how: str, unique: bool = False) -> None:
        buckets: Dict[Hashable, Tuple[List[int], List[int]]] = defaultdict(lambda: ([], []))
        for side, items, left in ((0, old, left_old), (1, new, left_new)):
            for index in sorted(left):
                k = key(items[index])
                if k is not None:
                    buckets[k][side].append(index)
        for olds, news in buckets.values():
            if not olds or not news or (unique and (len(olds) > 1 or len(news) > 1)):
                continue
            for i, j in zip(olds, news):
                pairs.append((i, j, how))
                left_old.discard(i)
                left_new.discard(j)

    trusted = _trust_handles(old, new, opts.match, lineage)
    if trusted:
        pair_by(lambda it: (it.space, it.handle, it.dxftype) if it.handle else None, "handle")
    pair_by(lambda it: (it.space, it.fingerprint), "geometry")
    # With trusted handles the leftovers really were deleted/created, so no guessing.
    for level in range(0 if trusted else max((len(it.similar) for it in old), default=0)):
        pair_by(_similarity_key(level), "similarity", unique=True)

    changes = [_compare_pair(old[i], new[j], how, opts.tolerance) for i, j, how in pairs]
    changes += [_single(ChangeKind.REMOVED, old[i]) for i in sorted(left_old)]
    changes += [_single(ChangeKind.ADDED, new[j]) for j in sorted(left_new)]
    return sorted(changes, key=_sort_key)


def diff_layers(old_doc: Drawing, new_doc: Drawing, opts: CompareOptions) -> List[LayerChange]:
    """Compare the LAYER tables of both drawings."""
    old, new = (
        {la.dxf.name.upper(): la for la in d.layers if opts.layer_selected(la.dxf.name)} for d in (old_doc, new_doc)
    )
    result = []
    for key in sorted(set(old) | set(new)):
        if key not in new:
            result.append(LayerChange(ChangeKind.REMOVED, old[key].dxf.name, "layer removed"))
        elif key not in old:
            p = layer_props(new[key])
            desc = f"layer added (color {fmt_color(p['color'])}, linetype {p['linetype']})"
            result.append(LayerChange(ChangeKind.ADDED, new[key].dxf.name, desc))
        else:
            a, b = ({k: v for k, v in layer_props(t[key]).items() if k not in opts.ignored} for t in (old, new))
            changes = diff_props(a, b, opts.tolerance)
            if changes:
                desc = describe_layer(changes, opts.tolerance)
                result.append(LayerChange(ChangeKind.MODIFIED, new[key].dxf.name, desc, changes))
    return sorted(result, key=lambda c: (KIND_ORDER[c.kind], c.name.upper()))


def diff_blocks(old_doc: Drawing, new_doc: Drawing, opts: CompareOptions, lineage: bool = False) -> List[BlockChange]:
    """Compare named block definitions (anonymous ``*`` blocks and XREFs are skipped)."""
    inner = replace(opts, layers=(), ignore_layers=())
    ignored, ndigits = opts.ignored, opts.ndigits
    old, new = ({b.name.upper(): b for b in named_blocks(doc)} for doc in (old_doc, new_doc))
    result = []
    for key in sorted(set(old) | set(new)):
        if key not in new:
            result.append(BlockChange(ChangeKind.REMOVED, old[key].name, f"block removed ({len(old[key])} entities)"))
            continue
        if key not in old:
            result.append(BlockChange(ChangeKind.ADDED, new[key].name, f"block added ({len(new[key])} entities)"))
            continue
        a, b = old[key], new[key]
        changes = diff_props({"base_point": base_point(a)}, {"base_point": base_point(b)}, opts.tolerance)
        items_a, items_b = ([_make_item(e, b.name, ignored, ndigits) for e in layout] for layout in (a, b))
        matched = match_entities(items_a, items_b, inner, lineage)
        inner_changes = [c for c in matched if c.kind is not ChangeKind.UNCHANGED]
        if not (changes or inner_changes):
            continue
        counts = Counter(c.kind for c in inner_changes)
        parts = [f"{counts[k]} {k}" for k in (ChangeKind.ADDED, ChangeKind.REMOVED, ChangeKind.MODIFIED) if counts[k]]
        parts += ["base point moved"] if changes else []
        details = [f"{c.kind}: {c.description}" for c in inner_changes[:50]]
        result.append(
            BlockChange(ChangeKind.MODIFIED, b.name, "content changed: " + ", ".join(parts), changes, details)
        )
    return sorted(result, key=lambda c: (KIND_ORDER[c.kind], c.name.upper()))


def compare(
    old: Source,
    new: Source,
    tolerance: float = 1e-6,
    *,
    layers: Optional[Sequence[str]] = None,
    ignore_layers: Optional[Sequence[str]] = None,
    ignore_props: Optional[Sequence[str]] = None,
    layouts: bool = False,
    match: str = "auto",
    options: Optional[CompareOptions] = None,
) -> DiffResult:
    """Compare two DXF drawings and return a :class:`~dxf_diff.model.DiffResult`.

    :param old: path of the OLD (original) DXF file or a loaded ezdxf ``Drawing``
    :param new: path of the NEW (revised) DXF file or a loaded ezdxf ``Drawing``
    :param tolerance: coordinates, lengths and angles (degrees) closer than this are equal
    :param layers: compare only entities on layers matching these wildcard patterns
    :param ignore_layers: skip entities on layers matching these wildcard patterns
    :param ignore_props: property names to ignore, e.g. ``["color", "linetype"]``
    :param layouts: also compare the paperspace layouts, not only modelspace
    :param match: ``"auto"`` (default), ``"handle"`` (always trust handles) or
        ``"geometry"`` (never trust handles, e.g. for files re-exported by another program)
    :param options: a ready :class:`CompareOptions`; overrides the keyword arguments
    :raises DxfDiffError: if a file is missing, not a DXF file or cannot be read
    """
    opts = options or CompareOptions(tolerance, layers or (), ignore_layers or (), ignore_props or (), layouts, match)
    old_doc, old_name = load_drawing(old)
    new_doc, new_name = load_drawing(new)
    lineage = same_lineage(old_doc, new_doc)
    entities = match_entities(_collect(old_doc, opts), _collect(new_doc, opts), opts, lineage)
    layer_changes = diff_layers(old_doc, new_doc, opts)
    block_changes = diff_blocks(old_doc, new_doc, opts, lineage)
    return DiffResult(old_name, new_name, entities, layer_changes, block_changes, asdict(opts), old_doc, new_doc)

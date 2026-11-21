"""Rebuild document lines from macOS Vision OCR observations (pure, no I/O)."""

from dataclasses import dataclass
from itertools import pairwise
from statistics import mean, median

MAX_OBSERVATIONS = 5_000
ROW_TOLERANCE = 0.5  # y-center distance to the row mean, in median heights
CELL_GAP = 1.5  # horizontal gap that starts a new column, in median heights
CELL_SEPARATOR = " | "
VALUE_ALIGN_TOLERANCE = 1.0  # max x-start offset from the value column, in median heights
CONTINUATION_GAP = (
    2.0  # max y-center step to the neighbouring row of the same cell, in median heights
)

type Box = tuple[float, float, float, float]  # x, y, w, h; normalized, top-left origin


class OcrRowsError(ValueError):
    """Raised when OCR input is too large to reconstruct safely."""


@dataclass(frozen=True)
class OcrObservation:
    text: str
    confidence: float
    box: Box


@dataclass(frozen=True)
class OcrLine:
    text: str
    cells: tuple[str, ...]
    confidence: float
    box: Box


def _y_center(item: OcrObservation) -> float:
    return item.box[1] + item.box[3] / 2


def _group_rows(items: list[OcrObservation], tolerance: float) -> list[list[OcrObservation]]:
    rows: list[list[OcrObservation]] = []
    for item in sorted(items, key=_y_center):
        if rows and abs(_y_center(item) - mean(_y_center(o) for o in rows[-1])) <= tolerance:
            rows[-1].append(item)
        else:
            rows.append([item])
    return rows


def _join(row: list[OcrObservation], gap_limit: float) -> str:
    parts = [row[0].text]
    for prev, cur in pairwise(row):
        gap = cur.box[0] - (prev.box[0] + prev.box[2])
        parts.append(CELL_SEPARATOR if gap > gap_limit else " ")
        parts.append(cur.text)
    return "".join(parts)


def _union(row: list[OcrObservation]) -> Box:
    left = min(o.box[0] for o in row)
    top = min(o.box[1] for o in row)
    right = max(o.box[0] + o.box[2] for o in row)
    bottom = max(o.box[1] + o.box[3] for o in row)
    return (left, top, right - left, bottom - top)


def _has_cell_break(row: list[OcrObservation], gap_limit: float) -> bool:
    return any(cur.box[0] - (prev.box[0] + prev.box[2]) > gap_limit for prev, cur in pairwise(row))


def _nearest_label(index: int, rows: list[list[OcrObservation]], labeled: list[int]) -> int:
    return min(labeled, key=lambda j: abs(_y_center(rows[j][0]) - _y_center(rows[index][0])))


def _assign_continuations(
    rows: list[list[OcrObservation]], labeled: list[int], value_x: float, height: float
) -> dict[int, int]:
    """Map continuation row index -> owning labeled row index (contiguous chains only)."""
    owners = {j: j for j in labeled}
    candidates = [
        i
        for i, row in enumerate(rows)
        if i not in owners
        and len(row) == 1
        and abs(row[0].box[0] - value_x) <= VALUE_ALIGN_TOLERANCE * height
    ]
    by_distance = sorted(
        ((i, _nearest_label(i, rows, labeled)) for i in candidates),
        key=lambda pair: abs(pair[0] - pair[1]),
    )
    for i, owner in by_distance:
        step = 1 if owner > i else -1
        neighbour = i + step
        gap = abs(_y_center(rows[i][0]) - _y_center(rows[neighbour][0]))
        if owners.get(neighbour) == owner and gap <= CONTINUATION_GAP * height:
            owners[i] = owner
    return {i: o for i, o in owners.items() if i != o}


def _merge_value_cells(
    rows: list[list[OcrObservation]], height: float
) -> list[list[OcrObservation]]:
    """Fold unlabeled value-column lines into the labeled row whose cell they continue."""
    ordered = [sorted(row, key=lambda o: o.box[0]) for row in rows]
    labeled = [i for i, row in enumerate(ordered) if _has_cell_break(row, CELL_GAP * height)]
    if not labeled:
        return ordered
    value_x = median(ordered[i][-1].box[0] for i in labeled)
    owners = _assign_continuations(ordered, labeled, value_x, height)
    merged: list[list[OcrObservation]] = []
    for i, row in enumerate(ordered):
        if i in owners:
            continue
        parts = [row[-1], *(ordered[k][0] for k, o in owners.items() if o == i)]
        if len(parts) == 1:
            merged.append(row)
            continue
        parts.sort(key=_y_center)
        cell = OcrObservation(
            text=" ".join(p.text for p in parts),
            confidence=min(p.confidence for p in parts),
            box=_union(parts),
        )
        merged.append([*row[:-1], cell])
    return sorted(merged, key=lambda r: _union(r)[1])


def reconstruct_lines(
    observations: list[OcrObservation] | tuple[OcrObservation, ...],
) -> tuple[OcrLine, ...]:
    """Group observations into top-to-bottom lines; wide gaps become " | " column breaks."""
    if len(observations) > MAX_OBSERVATIONS:
        message = f"too many OCR observations: {len(observations)} > {MAX_OBSERVATIONS}"
        raise OcrRowsError(message)
    items = [o for o in observations if o.text.strip()]
    if not items:
        return ()
    height = median(o.box[3] for o in items)
    merged = _merge_value_cells(_group_rows(items, ROW_TOLERANCE * height), height)
    return tuple(
        OcrLine(
            text=_join(ordered, CELL_GAP * height),
            cells=tuple(o.text for o in ordered),
            confidence=min(o.confidence for o in ordered),
            box=_union(ordered),
        )
        for ordered in merged
    )

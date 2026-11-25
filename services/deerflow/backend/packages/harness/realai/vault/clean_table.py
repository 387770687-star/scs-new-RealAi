"""Smart table cleaning: drop geometry columns, truncate huge cells."""

from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_GEOM_COL_RE = re.compile(r"^(geometry|geom|wkt|shape|the_geom)$", re.IGNORECASE)
MAX_CELL_CHARS = 2000


@dataclass(slots=True)
class CleanResult:
    csv_text: str
    dropped_columns: list[str]
    truncated_cells: int
    row_count: int


def is_geometry_column(name: str) -> bool:
    return bool(_GEOM_COL_RE.match((name or "").strip()))


def clean_csv_bytes(data: bytes, *, max_cell: int = MAX_CELL_CHARS) -> CleanResult:
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return CleanResult("", [], 0, 0)

    header = rows[0]
    keep_idx: list[int] = []
    dropped: list[str] = []
    for i, col in enumerate(header):
        if is_geometry_column(col):
            dropped.append(col)
        else:
            keep_idx.append(i)

    if not keep_idx:
        # keep all non-empty if somehow all geom — should not happen
        keep_idx = list(range(len(header)))
        dropped = []

    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    new_header = [header[i] for i in keep_idx]
    writer.writerow(new_header)
    truncated = 0
    data_rows = 0
    for row in rows[1:]:
        if not any(cell.strip() for cell in row):
            continue
        data_rows += 1
        cleaned: list[str] = []
        for i in keep_idx:
            cell = row[i] if i < len(row) else ""
            if len(cell) > max_cell:
                cell = cell[:max_cell] + "…"
                truncated += 1
            cleaned.append(cell)
        writer.writerow(cleaned)

    return CleanResult(
        csv_text=out.getvalue(),
        dropped_columns=dropped,
        truncated_cells=truncated,
        row_count=data_rows,
    )


def clean_csv_text(text: str, *, max_cell: int = MAX_CELL_CHARS) -> CleanResult:
    return clean_csv_bytes(text.encode("utf-8"), max_cell=max_cell)


def strip_geometry_from_excerpt_columns(columns: list[str]) -> list[str]:
    return [c for c in columns if not is_geometry_column(c)]

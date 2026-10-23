from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

import pandas as pd


DANGEROUS_FORMULA_PREFIXES = ("=", "+", "-", "@")


def export_csv(
    records: Iterable[Mapping[str, object]],
    columns: Sequence[str],
) -> bytes:
    """Create an Excel-safe UTF-8 CSV from allowlisted columns."""
    safe_rows = []
    for record in records:
        safe_rows.append(
            {column: _safe_cell(record.get(column, "")) for column in columns}
        )
    frame = pd.DataFrame(safe_rows, columns=columns)
    return frame.to_csv(index=False, lineterminator="\n").encode("utf-8-sig")


def _safe_cell(value: object) -> object:
    if not isinstance(value, str):
        return value
    if value.lstrip().startswith(DANGEROUS_FORMULA_PREFIXES):
        return "'" + value
    return value

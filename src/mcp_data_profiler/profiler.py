"""Dataset profiling, independent of any MCP or transport concern.

The public entry point is :func:`profile_dataset`, which turns a file on disk
into a plain dict. Keeping this module free of MCP imports means the profiling
logic can be unit tested directly and reused as an ordinary library.
"""

from __future__ import annotations

import csv
import json
import math
import os
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

# Formats we can read, mapped from extension to a loader key.
_EXTENSIONS = {
    ".csv": "csv",
    ".tsv": "csv",
    ".txt": "csv",
    ".parquet": "parquet",
    ".pq": "parquet",
    ".json": "json",
    ".jsonl": "jsonl",
    ".ndjson": "jsonl",
    ".xlsx": "excel",
    ".xlsm": "excel",
    ".xls": "excel",
}

# Profiling a sample keeps huge files cheap. Every response says which of the
# two it used, because a silently sampled statistic is a wrong statistic.
DEFAULT_SAMPLE_ROWS = 50_000

# Output caps. The whole point of this tool is to be cheaper than pasting the
# file, so the response has to stay small no matter how wide the input is.
DEFAULT_MAX_COLUMNS = 100
DEFAULT_TOP_K = 5
_MAX_STRING_LEN = 80

# A text column with this share of distinct values looks like an identifier
# rather than a category worth summarising.
_HIGH_CARDINALITY_RATIO = 0.9


# Delimiters worth considering for a .csv. Semicolon matters more than it
# looks: most European open data uses it, because the comma is a decimal mark.
_CANDIDATE_DELIMITERS = (",", ";", "\t", "|")


class ProfileError(Exception):
    """Raised for bad input: missing file, unreadable file, unknown format."""


def _sniff_delimiter(path: Path) -> str:
    """Infer a CSV's delimiter by testing candidates for a consistent shape.

    Deliberately *not* :class:`csv.Sniffer` or ``pandas`` ``sep=None``: those
    infer from character frequency and will happily split a header like
    ``letter`` on its ``t``. Here only real delimiter characters are ever
    considered, and a candidate has to produce a stable column count across
    many lines before it is accepted, so a wrong guess is very unlikely.
    """
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            sample = [line for _, line in zip(range(50), handle)]
    except OSError:
        return ","

    sample = [line for line in sample if line.strip()]
    if not sample:
        return ","

    best, best_width = ",", 0
    for delimiter in _CANDIDATE_DELIMITERS:
        try:
            widths = [len(row) for row in csv.reader(sample, delimiter=delimiter) if row]
        except csv.Error:
            continue
        if not widths:
            continue
        width, hits = Counter(widths).most_common(1)[0]
        # Demand a majority agree on the column count; free-text rows and
        # quoted newlines make a few outliers normal.
        if width > best_width and hits >= max(2, len(widths) * 0.6):
            best, best_width = delimiter, width

    # best_width <= 1 means nothing split the file, i.e. a single column.
    return best if best_width > 1 else ","


def detect_format(path: Path) -> str:
    """Return the loader key for ``path``, based on its extension."""
    suffix = path.suffix.lower()
    if suffix == ".gz":
        # e.g. data.csv.gz -> look at the extension underneath.
        suffix = Path(path.stem).suffix.lower()
    fmt = _EXTENSIONS.get(suffix)
    if fmt is None:
        supported = ", ".join(sorted(_EXTENSIONS))
        raise ProfileError(f"Unsupported file extension {suffix!r}. Supported: {supported}")
    return fmt


def _exact_row_count(path: Path, fmt: str) -> int | None:
    """Total rows without loading the data, when the format makes that cheap.

    Returns ``None`` when finding out would cost as much as reading the file.
    """
    try:
        if fmt == "parquet":
            import pyarrow.parquet as pq

            return pq.ParquetFile(path).metadata.num_rows
        if fmt == "csv":
            # Count newlines in binary chunks, then discount the header.
            with path.open("rb") as handle:
                lines = sum(chunk.count(b"\n") for chunk in iter(lambda: handle.read(1 << 20), b""))
            return max(lines - 1, 0)
        if fmt == "jsonl":
            with path.open("rb") as handle:
                return sum(chunk.count(b"\n") for chunk in iter(lambda: handle.read(1 << 20), b""))
    except Exception:
        # Row count is a nicety; never fail the profile over it.
        return None
    return None


def list_excel_sheets(path: Path) -> list[str]:
    """Return the sheet names in a workbook, or ``[]`` if they can't be read."""
    try:
        with pd.ExcelFile(path) as workbook:
            return list(workbook.sheet_names)
    except Exception:
        return []


def _load(
    path: Path,
    fmt: str,
    sample_rows: int | None,
    sheet: str | int | None = None,
) -> tuple[pd.DataFrame, bool]:
    """Load ``path`` into a DataFrame, returning ``(frame, was_sampled)``."""
    # Read one extra row so we can tell "exactly at the limit" from "truncated".
    limit = None if sample_rows is None else sample_rows + 1
    try:
        if fmt == "csv":
            sep = "\t" if path.suffix.lower() == ".tsv" else _sniff_delimiter(path)
            # utf-8-sig strips the byte-order mark that Excel and many public
            # data portals emit; without it the first column is named "﻿Date".
            frame = pd.read_csv(path, sep=sep, nrows=limit, encoding="utf-8-sig")
        elif fmt == "parquet":
            frame = pd.read_parquet(path)
        elif fmt == "json":
            frame = pd.read_json(path)
        elif fmt == "jsonl":
            frame = pd.read_json(path, lines=True, nrows=limit)
        elif fmt == "excel":
            frame = pd.read_excel(path, sheet_name=sheet if sheet is not None else 0, nrows=limit)
        else:  # pragma: no cover - detect_format already rejected these
            raise ProfileError(f"Unsupported format {fmt!r}")
    except ProfileError:
        raise
    except Exception as exc:
        raise ProfileError(f"Could not read {path.name} as {fmt}: {exc}") from exc

    was_sampled = False
    if sample_rows is not None and len(frame) > sample_rows:
        frame = frame.head(sample_rows)
        was_sampled = True
    return frame, was_sampled


def _clean(value: Any) -> Any:
    """Coerce a pandas scalar into something JSON can represent."""
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        # JSON has no NaN/Infinity; emitting them produces invalid documents.
        return None
    if isinstance(value, (pd.Timestamp, pd.Period)):
        return str(value)
    if hasattr(value, "item"):  # numpy scalar
        try:
            return _clean(value.item())
        except (ValueError, AttributeError):
            return str(value)
    if isinstance(value, str) and len(value) > _MAX_STRING_LEN:
        return value[:_MAX_STRING_LEN] + "…"
    if isinstance(value, (int, bool, str)):
        return value
    if isinstance(value, float):
        return round(value, 6)
    return str(value)


def _is_text_like(series: pd.Series) -> bool:
    """True for text columns, across pandas versions.

    pandas 3 gives string columns a dedicated ``str`` dtype; pandas 2 leaves
    them as ``object``. Checking only for ``object`` silently disables every
    text heuristic on pandas 3, so accept both.
    """
    return pd.api.types.is_string_dtype(series) or series.dtype == object


def _looks_numeric(series: pd.Series) -> bool:
    """True if a text column is really numbers that were never parsed."""
    values = series.dropna().astype(str).head(200)
    if values.empty:
        return False
    converted = pd.to_numeric(values, errors="coerce")
    return bool(converted.notna().all())


def _looks_temporal(series: pd.Series) -> bool:
    """True if a text column is really dates that were never parsed."""
    values = series.dropna().astype(str).head(200)
    if values.empty:
        return False
    # Purely numeric text is a number, not a date, even though the date parser
    # will happily accept it.
    if pd.to_numeric(values, errors="coerce").notna().all():
        return False
    converted = pd.to_datetime(values, errors="coerce", format="mixed")
    return bool(converted.notna().all())


def _has_mixed_types(series: pd.Series) -> bool:
    """True if one object column holds several unrelated Python types."""
    if series.dtype != object:
        return False
    kinds = {type(v).__name__ for v in series.dropna().head(200)}
    return len(kinds) > 1


def _profile_column(name: str, series: pd.Series, top_k: int) -> dict[str, Any]:
    """Summarise a single column, including any quality flags it earns."""
    total = len(series)
    null_count = int(series.isna().sum())
    non_null = series.dropna()
    unique_count = int(non_null.nunique())

    column: dict[str, Any] = {
        "name": name,
        "dtype": str(series.dtype),
        "null_count": null_count,
        "null_pct": round(100 * null_count / total, 2) if total else 0.0,
        "unique_count": unique_count,
    }

    flags: list[str] = []
    if total and null_count == total:
        flags.append("all_null")
    elif unique_count == 1:
        flags.append("constant")

    if not non_null.empty:
        if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
            described = non_null.describe()
            column["stats"] = {
                "min": _clean(described.get("min")),
                "max": _clean(described.get("max")),
                "mean": _clean(described.get("mean")),
                "std": _clean(described.get("std")),
                "q25": _clean(described.get("25%")),
                "median": _clean(described.get("50%")),
                "q75": _clean(described.get("75%")),
            }
        elif pd.api.types.is_datetime64_any_dtype(series):
            column["stats"] = {"min": _clean(non_null.min()), "max": _clean(non_null.max())}
        else:
            is_high_cardinality = (
                _is_text_like(series)
                and unique_count > 1
                and unique_count / len(non_null) >= _HIGH_CARDINALITY_RATIO
            )
            # For a near-unique column, "top values" is a list of counts of 1 —
            # noise that costs tokens and tells the reader nothing.
            if not is_high_cardinality:
                counts = non_null.value_counts().head(top_k)
                column["top_values"] = [
                    {"value": _clean(value), "count": int(count)} for value, count in counts.items()
                ]
            if _is_text_like(series):
                if is_high_cardinality:
                    flags.append("high_cardinality_possible_id")
                if _has_mixed_types(non_null):
                    flags.append("mixed_types")
                elif _looks_numeric(non_null):
                    flags.append("numeric_stored_as_text")
                elif _looks_temporal(non_null):
                    flags.append("date_stored_as_text")

        column["sample_values"] = [_clean(v) for v in non_null.head(3).tolist()]

    if flags:
        column["flags"] = flags
    return column


def profile_dataset(
    path: str | os.PathLike[str],
    *,
    sample_rows: int | None = DEFAULT_SAMPLE_ROWS,
    max_columns: int = DEFAULT_MAX_COLUMNS,
    top_k: int = DEFAULT_TOP_K,
    sheet: str | int | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Profile a dataset file and return a compact, JSON-safe summary.

    Args:
        path: File to profile.
        sample_rows: Row cap for profiling; ``None`` reads the whole file.
        max_columns: Cap on how many columns are described in detail.
        top_k: How many frequent values to list per categorical column.
        sheet: For Excel, which sheet to profile (name or zero-based index).
            Defaults to the first sheet.
        root: If given, ``path`` must resolve inside this directory.

    Raises:
        ProfileError: The path is missing, outside ``root``, or unreadable.
    """
    target = Path(path).expanduser()
    try:
        target = target.resolve(strict=True)
    except (OSError, FileNotFoundError) as exc:
        raise ProfileError(f"No such file: {path}") from exc

    if root is not None:
        # Compare canonical paths so symlinks and ".." cannot escape the root.
        root_resolved = Path(root).expanduser().resolve()
        if not target.is_relative_to(root_resolved):
            raise ProfileError(f"Path is outside the allowed root directory: {root_resolved}")

    if not target.is_file():
        raise ProfileError(f"Not a file: {target}")

    fmt = detect_format(target)

    sheets: list[str] = []
    if fmt == "excel":
        sheets = list_excel_sheets(target)
        if sheet is not None and isinstance(sheet, str) and sheets and sheet not in sheets:
            raise ProfileError(f"No sheet named {sheet!r}. Available sheets: {sheets}")

    frame, was_sampled = _load(target, fmt, sample_rows, sheet=sheet)
    total_rows = _exact_row_count(target, fmt) if was_sampled else len(frame)

    all_columns = list(frame.columns)
    shown = all_columns[:max_columns]

    file_info: dict[str, Any] = {
        "name": target.name,
        "format": fmt,
        "size_bytes": target.stat().st_size,
    }

    if sheets:
        # A workbook's first sheet is often a title or notes page. Profiling it
        # silently and saying nothing would report an empty dataset as clean,
        # so always name the sheet used and list the alternatives.
        if isinstance(sheet, int):
            profiled = sheets[sheet] if 0 <= sheet < len(sheets) else str(sheet)
        else:
            profiled = sheet if sheet is not None else sheets[0]
        file_info["sheet_profiled"] = profiled
        if len(sheets) > 1:
            file_info["available_sheets"] = sheets
            file_info["sheets_note"] = (
                f"This workbook has {len(sheets)} sheets; only {profiled!r} was "
                "profiled. Pass sheet=<name> to profile a different one."
            )

    profile: dict[str, Any] = {
        "file": file_info,
        "shape": {
            "rows_profiled": len(frame),
            "total_rows": total_rows,
            "columns": len(all_columns),
        },
        "sampled": was_sampled,
        "columns": [_profile_column(str(c), frame[c], top_k) for c in shown],
    }

    if was_sampled:
        profile["sampling_note"] = (
            f"Statistics come from the first {len(frame):,} rows, not the whole file. "
            "Pass sample_rows=null to profile every row."
        )

    if len(shown) < len(all_columns):
        omitted = len(all_columns) - len(shown)
        profile["columns_omitted"] = omitted
        profile["columns_note"] = (
            f"{omitted} of {len(all_columns)} columns are not detailed here "
            f"(max_columns={max_columns}). Raise max_columns to see more."
        )

    # Duplicate detection needs hashable cells; unhashable ones (lists, dicts)
    # come from nested JSON and simply make the check inapplicable.
    try:
        profile["duplicate_rows"] = int(frame.duplicated().sum())
    except TypeError:
        profile["duplicate_rows"] = None

    return profile


def profile_to_json(profile: dict[str, Any]) -> str:
    """Serialise a profile to JSON, rejecting non-finite floats loudly."""
    return json.dumps(profile, indent=2, allow_nan=False, default=str)

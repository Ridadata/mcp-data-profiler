"""Profile datasets from the command line and summarise what was found.

With no arguments it generates a small messy dataset in a temporary directory
and profiles that, so the demo works on a fresh clone:

    python demo.py

Pass paths to profile real files instead:

    python demo.py data/orders.csv data/events.parquet
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

from mcp_data_profiler import profile_dataset, profile_to_json


def build_sample(directory: Path) -> Path:
    """Write a dataset containing one of every problem the profiler flags."""
    import pandas as pd

    rows = 5_000
    frame = pd.DataFrame(
        {
            # Distinct for every row: an identifier, not a feature.
            "order_id": [f"ORD-{i:06d}" for i in range(rows)],
            "customer_region": ["AMER", "APAC", "EMEA", "LATAM"] * (rows // 4),
            "amount_eur": [round(2 + (i * 37 % 1368) + 0.65, 2) for i in range(rows)],
            # Never varies.
            "currency": ["EUR"] * rows,
            # A real timestamp, but typed as text, so it sorts wrong.
            "ordered_at": pd.date_range("2024-01-01", periods=rows, freq="h").astype(str),
            # Entirely empty.
            "notes": [None] * rows,
        }
    )
    path = directory / "orders.csv"
    frame.to_csv(path, index=False)
    return path


def human(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f}{unit}"
        size /= 1024
    return f"{size:.0f}TB"


def report(path: str) -> None:
    """Profile one file and print a short summary of it."""
    name = os.path.basename(path)
    if not os.path.exists(path):
        print(f"\n{name}: not found, skipped")
        return

    started = time.time()
    try:
        profile = profile_dataset(path)
    except Exception as exc:  # keep going so one bad file cannot end the run
        print(f"\n{name}: ERROR {exc}")
        return
    elapsed = time.time() - started

    rendered = profile_to_json(profile)
    raw = os.path.getsize(path)
    shape = profile["shape"]
    sheet = profile["file"].get("sheet_profiled")

    print(f"\n{'-' * 78}")
    print(name + (f"   [sheet: {sheet}]" if sheet else ""))
    print("-" * 78)

    rows = shape["total_rows"] or shape["rows_profiled"]
    print(
        f"  {rows:,} rows x {shape['columns']} cols   "
        f"file {human(raw)} -> profile {human(len(rendered))}   "
        f"({raw / len(rendered):,.0f}x smaller)   {elapsed:.1f}s"
    )
    if profile["sampled"]:
        print(f"  sampled: profiled first {shape['rows_profiled']:,} rows (disclosed)")
    if profile.get("duplicate_rows"):
        print(f"  duplicate rows: {profile['duplicate_rows']:,}")
    if profile["file"].get("sheets_note"):
        print(f"  {profile['file']['sheets_note']}")

    findings = [(flag, c["name"]) for c in profile["columns"] for flag in c.get("flags", [])]
    findings += [
        (f"{c['null_pct']:.0f}% null", c["name"]) for c in profile["columns"] if c["null_pct"] >= 50
    ]

    if findings:
        print("  findings:")
        for flag, column in findings[:12]:
            print(f"      {flag:<32} {column[:38]}")
        if len(findings) > 12:
            print(f"      ... and {len(findings) - 12} more")
    else:
        print("  findings: none - this file looks clean")


def main() -> None:
    print("=" * 78)
    print("mcp-data-profiler")
    print("=" * 78)

    paths = sys.argv[1:]
    if paths:
        for path in paths:
            report(path)
    else:
        # No arguments: profile a generated sample so a fresh clone still works.
        with tempfile.TemporaryDirectory() as tmp:
            print("\nNo paths given - profiling a generated sample dataset.")
            print("Pass file paths to profile your own data instead.")
            report(str(build_sample(Path(tmp))))

    print(f"\n{'=' * 78}")


if __name__ == "__main__":
    main()

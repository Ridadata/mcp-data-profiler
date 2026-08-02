"""MCP server exposing the dataset profiler over stdio.

Thin adapter: all real work lives in :mod:`mcp_data_profiler.profiler`.

Note for contributors: this speaks the MCP protocol over stdout, so nothing
here may ``print()``. Diagnostics must go to stderr.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from .profiler import (
    DEFAULT_MAX_COLUMNS,
    DEFAULT_SAMPLE_ROWS,
    DEFAULT_TOP_K,
    ProfileError,
    profile_dataset,
)

__version__ = "0.1.0"

mcp = MCPServer(
    name="data-profiler",
    version=__version__,
    instructions=(
        "Profiles local datasets (CSV, Parquet, JSON, JSONL, Excel). Use the "
        "profile_dataset tool to understand a data file's structure and quality "
        "instead of reading the raw file into the conversation."
    ),
)

# Set by main() when the user passes --root.
_root: Path | None = None


@mcp.tool(
    # Named explicitly: the Python function carries a _tool suffix only to
    # avoid shadowing the imported profile_dataset, which clients shouldn't see.
    name="profile_dataset",
    annotations=ToolAnnotations(
        title="Profile a dataset file",
        read_only_hint=True,
        # It only ever touches the local filesystem.
        open_world_hint=False,
    )
)
def profile_dataset_tool(
    path: str,
    sample_rows: int | None = DEFAULT_SAMPLE_ROWS,
    max_columns: int = DEFAULT_MAX_COLUMNS,
    top_k: int = DEFAULT_TOP_K,
    sheet: str | None = None,
) -> dict[str, Any]:
    """Summarise the structure and quality of a local data file.

    Call this whenever you need to understand a dataset — its columns, types,
    ranges, missing values, or quality problems — before analysing it, writing
    code against it, or answering questions about it. Prefer this over reading
    the file directly: it returns a compact summary instead of raw rows, so it
    works on files far too large to read, at a small fraction of the tokens.

    Reports per column: dtype, null count and percentage, distinct count,
    sample values, quartiles for numbers, date ranges, and the most frequent
    values for categories. Flags likely problems: all-null and constant
    columns, probable ID columns, mixed types, and numbers or dates that were
    stored as text.

    Args:
        path: Path to the file. Supports .csv, .tsv, .parquet, .json, .jsonl,
            .xlsx, and .xls.
        sample_rows: Profile at most this many rows. Pass null to read every
            row, which is slower on large files but makes all statistics exact.
            The result always states whether it was sampled.
        max_columns: Describe at most this many columns, so the response stays
            small on very wide tables. The true column count is always
            reported.
        top_k: How many of the most frequent values to list per categorical
            column.
        sheet: For Excel workbooks, the name of the sheet to profile. Defaults
            to the first sheet, which is often a title or notes page rather
            than the data. The result lists every available sheet, so if the
            one profiled looks empty or wrong, call again naming another.

    Returns:
        A profile with file info, shape, per-column detail, and duplicate row
        count.
    """
    try:
        return profile_dataset(
            path,
            sample_rows=sample_rows,
            max_columns=max_columns,
            top_k=top_k,
            sheet=sheet,
            root=_root,
        )
    except ProfileError as exc:
        # A predictable, actionable problem (missing file, bad format, blocked
        # path). Surface the message so the model can correct itself, rather
        # than a traceback.
        raise ValueError(str(exc)) from exc


def main() -> None:
    """Entry point for the ``mcp-data-profiler`` command."""
    parser = argparse.ArgumentParser(
        prog="mcp-data-profiler",
        description="MCP server that profiles local datasets.",
    )
    parser.add_argument(
        "--root",
        metavar="DIR",
        default=None,
        help=(
            "Restrict profiling to files inside DIR. Without this, any file "
            "readable by this process can be profiled."
        ),
    )
    args = parser.parse_args()

    global _root
    if args.root is not None:
        root = Path(args.root).expanduser()
        try:
            root = root.resolve(strict=True)
        except (OSError, FileNotFoundError):
            parser.error(f"--root directory does not exist: {args.root}")
        if not root.is_dir():
            parser.error(f"--root is not a directory: {root}")
        _root = root
        print(f"data-profiler: restricted to {root}", file=sys.stderr)

    # Defaults to stdio; run() is synchronous.
    mcp.run()


if __name__ == "__main__":
    main()

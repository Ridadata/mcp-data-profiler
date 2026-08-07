"""Render the MCP conversation recorded as docs/mcp-demo.gif.

The conversation is staged — the question and the wording of the answer are
scripted, because a GIF has to be the same every time it is recorded. The
*data* is not: this calls the real ``profile_dataset`` on a real file and every
number, dtype, and quality flag on screen is read back out of the profile it
returns. Nothing here can claim a finding the profiler did not make.

The dataset is the one ``demo.py`` generates, so both recordings describe the
same file.

Run it directly to preview the timing outside VHS:

    python docs/vhs/mcp_session.py --speed 2
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from demo import build_sample  # noqa: E402
from mcp_data_profiler import profile_dataset, profile_to_json  # noqa: E402

# ANSI, kept to the base 16 colours so the VHS theme decides the actual hues.
DIM = "\033[2m"
BOLD = "\033[1m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
OFF = "\033[0m"

# The two markers Claude Code uses for a tool call and its result.
BULLET = "⏺"  # ⏺
BRANCH = "⎿"  # ⎿

QUESTION = "what's in orders.csv?"

# Flags that mean the column is wrong, as opposed to merely uninteresting: an
# ID column is fine, a date stored as text is a bug waiting to happen.
DEFECTS = ("all_null", "constant", "date_stored_as_text", "numeric_stored_as_text", "mixed_types")

# Worst-first, so a column carrying two flags is described by the worse one.
FLAG_TEXT = {
    "all_null": "entirely null",
    "constant": "constant",
    "date_stored_as_text": "dates stored as text",
    "numeric_stored_as_text": "numbers stored as text",
    "mixed_types": "mixed types",
    "high_cardinality_possible_id": "looks like an ID",
}

speed = 1.0


def pause(seconds: float) -> None:
    time.sleep(seconds / speed)


def write(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


def stream(text: str, indent: str = "", per_word: float = 0.034) -> None:
    """Print a line the way a model emits it: a word at a time."""
    write(indent)
    for index, word in enumerate(text.split(" ")):
        write(word if index == 0 else " " + word)
        pause(per_word)
    write("\n")


def human(size: float) -> str:
    """Byte count at a readable precision: 2.3 KB, but 237 KB."""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:,.1f} {unit}" if size < 10 and unit != "B" else f"{size:,.0f} {unit}"
        size /= 1024
    return f"{size:,.1f} TB"


def num(value: float) -> str:
    """Format a statistic without trailing-zero noise."""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text or "0"


def plural(count: int, noun: str) -> str:
    return f"{count:,} {noun}" if count == 1 else f"{count:,} {noun}s"


def describe(column: dict) -> tuple[str, str]:
    """Return (value summary, note) for one profiled column."""
    flags = column.get("flags", [])
    worst = next((flag for flag in FLAG_TEXT if flag in flags), None)

    stats = column.get("stats")
    if stats and "q25" in stats:
        summary = f"{num(stats['min'])} – {num(stats['max'])}"  # noqa: RUF001 - en dash, on purpose
        note = f"{DIM}median {num(stats['median'])}{OFF}"
    elif stats:
        summary = f"{stats['min']} .. {stats['max']}"
        note = ""
    elif not column.get("sample_values"):  # nothing to sample: the column is empty
        summary = "0 values"
        note = ""
    elif column.get("top_values"):
        values = [str(item["value"]) for item in column["top_values"]]
        summary = plural(column["unique_count"], "value")
        joined = f" {DIM}·{OFF} ".join(values[:4])
        note = f"{DIM}{joined}{OFF}" if len(values) <= 4 else f"{DIM}{values[0]} and others{OFF}"
    else:
        summary = f"{column['unique_count']:,} distinct"
        note = ""

    if worst == "constant" and column.get("top_values"):
        note = f'constant ("{column["top_values"][0]["value"]}")'
    elif worst:
        note = FLAG_TEXT[worst]

    if worst:
        note = f"{YELLOW}⚠ {note}{OFF}"
    return summary, note


def defect_sentence(columns: list[dict]) -> list[str]:
    """Describe the real defects, in the profiler's own terms."""
    by_flag = {flag: [c["name"] for c in columns if flag in c.get("flags", [])] for flag in DEFECTS}
    clauses = []
    for name in by_flag["constant"]:
        clauses.append(f"{name} never varies")
    for name in by_flag["all_null"]:
        clauses.append(f"{name} is entirely empty")
    for name in by_flag["date_stored_as_text"]:
        clauses.append(f"{name} sorts as text")
    for name in by_flag["numeric_stored_as_text"]:
        clauses.append(f"{name} compares as text")

    if not clauses:
        return ["Nothing is flagged: this file is clean."]

    sentence = ", ".join(clauses[:-1]) + (" and " if len(clauses) > 1 else "") + clauses[-1]
    lines = ["So: " + sentence + "."]
    if by_flag["date_stored_as_text"]:
        lines.append('That last one makes "2024-10-01" < "2024-9-01" true, so anything')
        lines.append("ordered by date downstream is quietly wrong.")
    return lines


def run(path: Path) -> None:
    # Wipe the command line that launched this, then hold: the tape is still
    # hidden here, and the lead-in absorbs however long the interpreter took
    # to start so the visible recording always opens on an empty frame.
    write("\033[2J\033[H")
    pause(1.0)

    # The question, typed by a person.
    write(f"{BOLD}> {OFF}")
    for character in QUESTION:
        write(character)
        pause(0.05)
    write("\n\n")
    pause(0.6)

    # The tool call.
    write(f'{GREEN}{BULLET}{OFF} profile_dataset(path: {CYAN}"{path.name}"{OFF})\n')
    pause(0.25)
    write(f"  {DIM}{BRANCH}  profiling...{OFF}")

    started = time.time()
    profile = profile_dataset(str(path))
    elapsed = time.time() - started
    pause(1.0)

    raw = path.stat().st_size
    rendered = len(profile_to_json(profile))
    shape = profile["shape"]
    write("\r\033[2K")  # drop the placeholder, keep the line
    # The multiplication signs are typography, not code; RUF001 is silenced.
    write(
        f"  {DIM}{BRANCH}{OFF}  {human(raw)} file {DIM}→{OFF} {human(rendered)} profile"
        f" {DIM}·{OFF} {shape['total_rows']:,} rows × {shape['columns']} columns"  # noqa: RUF001
        f" {DIM}·{OFF} {raw / rendered:,.0f}× smaller {DIM}·{OFF} {elapsed:.1f}s\n\n"  # noqa: RUF001
    )
    pause(0.7)

    # The answer.
    columns = profile["columns"]
    broken = [c for c in columns if any(f in DEFECTS for f in c.get("flags", []))]
    write(f"{GREEN}{BULLET}{OFF} ")
    stream(f"{path.name} holds {shape['total_rows']:,} orders across {shape['columns']} columns.")
    stream(f"{len(broken)} of the columns are already broken:", indent="  ")
    write("\n")
    pause(0.2)

    width = max(len(c["name"]) for c in columns)
    for column in columns:
        summary, note = describe(column)
        name, dtype = column["name"], column["dtype"]
        write(f"    {name:<{width}}  {DIM}{dtype:<8}{OFF}  {summary:<16}  {note}\n")
        pause(0.26)

    write("\n")
    pause(0.35)
    for line in defect_sentence(columns):
        stream(line, indent="  ")
    pause(2.0)


def main() -> None:
    global speed

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--speed", type=float, default=1.0, help="playback multiplier")
    speed = parser.parse_args().speed

    directory = Path(tempfile.mkdtemp(prefix="mcp-demo-"))
    try:
        run(build_sample(directory))
    finally:
        shutil.rmtree(directory, ignore_errors=True)


if __name__ == "__main__":
    main()

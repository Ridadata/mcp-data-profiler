from __future__ import annotations

import json

import pandas as pd
import pytest

from mcp_data_profiler.profiler import (
    ProfileError,
    detect_format,
    profile_dataset,
    profile_to_json,
)


def _column(profile: dict, name: str) -> dict:
    return next(c for c in profile["columns"] if c["name"] == name)


@pytest.fixture
def messy_csv(tmp_path):
    """A CSV carrying one of every problem the flags are meant to catch."""
    frame = pd.DataFrame(
        {
            "id": ["a1", "b2", "c3", "d4", "e5", "e5"],
            "constant": ["same"] * 6,
            "all_null": [None] * 6,
            "numeric_text": ["1", "2", "3", "4", "5", "5"],
            "date_text": [
                "2024-01-01",
                "2024-02-01",
                "2024-03-01",
                "2024-04-01",
                "2024-05-01",
                "2024-05-01",
            ],
            "real_number": [1.5, 2.5, 3.5, 4.5, 5.5, 5.5],
            "category": ["x", "y", "x", "y", "x", "x"],
            "with_nulls": [1.0, None, 3.0, None, 5.0, 5.0],
        }
    )
    path = tmp_path / "messy.csv"
    frame.to_csv(path, index=False)
    return path


def test_detects_format_from_extension():
    assert detect_format(pd.io.common.Path("a.csv")) == "csv"
    assert detect_format(pd.io.common.Path("a.parquet")) == "parquet"
    assert detect_format(pd.io.common.Path("a.jsonl")) == "jsonl"


def test_rejects_unknown_extension(tmp_path):
    path = tmp_path / "notes.docx"
    path.write_text("x")
    with pytest.raises(ProfileError, match="Unsupported file extension"):
        profile_dataset(path)


def test_rejects_missing_file(tmp_path):
    with pytest.raises(ProfileError, match="No such file"):
        profile_dataset(tmp_path / "ghost.csv")


def test_reports_shape_and_duplicates(messy_csv):
    profile = profile_dataset(messy_csv)
    assert profile["shape"]["rows_profiled"] == 6
    assert profile["shape"]["columns"] == 8
    assert profile["sampled"] is False
    # The last row is an exact repeat of the one before it.
    assert profile["duplicate_rows"] == 1


@pytest.mark.parametrize(
    ("column", "flag"),
    [
        ("constant", "constant"),
        ("all_null", "all_null"),
    ],
)
def test_quality_flags(messy_csv, column, flag):
    profile = profile_dataset(messy_csv)
    assert flag in _column(profile, column).get("flags", [])


def test_csv_numbers_are_parsed_so_no_text_flag(messy_csv):
    """Reading a CSV, pandas turns "1","2" into integers on its own.

    So the mis-typing flags must NOT fire here — there is nothing wrong.
    """
    column = _column(profile_dataset(messy_csv), "numeric_text")
    assert column["dtype"].startswith("int")
    assert "numeric_stored_as_text" not in column.get("flags", [])


@pytest.mark.parametrize(
    ("column", "flag"),
    [
        ("numeric_text", "numeric_stored_as_text"),
        ("date_text", "date_stored_as_text"),
    ],
)
def test_mistyped_columns_flagged_in_parquet(tmp_path, column, flag):
    """The real mis-typing case: a producer wrote numbers/dates as strings.

    Parquet preserves that declared string type, unlike CSV where pandas
    re-infers it away.
    """
    path = tmp_path / "typed.parquet"
    pd.DataFrame(
        {
            "numeric_text": ["1", "2", "3", "4", "5", "6"],
            "date_text": [
                "2024-01-01",
                "2024-02-01",
                "2024-03-01",
                "2024-04-01",
                "2024-05-01",
                "2024-06-01",
            ],
            # Repeats, so this reads as a genuine category rather than an id.
            "genuine_text": ["alpha", "beta", "alpha", "beta", "alpha", "beta"],
        }
    ).to_parquet(path, index=False)

    profile = profile_dataset(path)

    assert flag in _column(profile, column).get("flags", [])
    # A column of real words must not be mistaken for a mis-typed one.
    genuine_flags = _column(profile, "genuine_text").get("flags", [])
    assert "numeric_stored_as_text" not in genuine_flags
    assert "date_stored_as_text" not in genuine_flags


def test_high_cardinality_column_flagged_as_possible_id(tmp_path):
    path = tmp_path / "ids.csv"
    pd.DataFrame(
        {
            "user_id": [f"u{i}" for i in range(50)],  # all distinct
            "tier": ["free", "paid"] * 25,  # only two values
        }
    ).to_csv(path, index=False)

    profile = profile_dataset(path)

    assert "high_cardinality_possible_id" in _column(profile, "user_id")["flags"]
    assert "high_cardinality_possible_id" not in _column(profile, "tier").get("flags", [])


def test_id_column_omits_useless_top_values(tmp_path):
    """For a near-unique column every count is 1, so listing them is noise."""
    path = tmp_path / "ids.csv"
    pd.DataFrame(
        {
            "user_id": [f"u{i}" for i in range(50)],
            "tier": ["free", "paid"] * 25,
        }
    ).to_csv(path, index=False)

    profile = profile_dataset(path)

    assert "top_values" not in _column(profile, "user_id")
    # A real category still gets them.
    assert _column(profile, "tier")["top_values"][0]["count"] == 25


def test_clean_columns_carry_no_flags(messy_csv):
    profile = profile_dataset(messy_csv)
    assert "flags" not in _column(profile, "real_number")
    assert "flags" not in _column(profile, "category")


def test_numeric_column_gets_stats(messy_csv):
    stats = _column(profile_dataset(messy_csv), "real_number")["stats"]
    assert stats["min"] == 1.5
    assert stats["max"] == 5.5
    assert stats["median"] == pytest.approx(4.0)


def test_categorical_column_gets_top_values(messy_csv):
    top = _column(profile_dataset(messy_csv), "category")["top_values"]
    assert top[0] == {"value": "x", "count": 4}


def test_null_counts_are_accurate(messy_csv):
    column = _column(profile_dataset(messy_csv), "with_nulls")
    assert column["null_count"] == 2
    assert column["null_pct"] == pytest.approx(33.33, abs=0.01)


def test_top_k_is_respected(tmp_path):
    path = tmp_path / "many.csv"
    pd.DataFrame({"letter": list("abcdefghij") * 3}).to_csv(path, index=False)
    top = _column(profile_dataset(path, top_k=3), "letter")["top_values"]
    assert len(top) == 3


# --- the two constraints the tool's value depends on -----------------------


def test_wide_frame_is_capped_and_says_so(tmp_path):
    """A wide table must not blow up the response, and must admit the cut."""
    path = tmp_path / "wide.csv"
    pd.DataFrame({f"col_{i}": [1, 2, 3] for i in range(250)}).to_csv(path, index=False)

    profile = profile_dataset(path, max_columns=10)

    assert len(profile["columns"]) == 10
    assert profile["shape"]["columns"] == 250  # true width still reported
    assert profile["columns_omitted"] == 240
    assert "max_columns" in profile["columns_note"]


def test_sampling_is_disclosed_with_true_total(tmp_path):
    """A sampled profile must be labelled and still report the real row count."""
    path = tmp_path / "big.csv"
    pd.DataFrame({"n": range(500)}).to_csv(path, index=False)

    profile = profile_dataset(path, sample_rows=100)

    assert profile["sampled"] is True
    assert profile["shape"]["rows_profiled"] == 100
    assert profile["shape"]["total_rows"] == 500  # counted without a full read
    assert "not the whole file" in profile["sampling_note"]


def test_not_sampled_when_file_fits(tmp_path):
    path = tmp_path / "small.csv"
    pd.DataFrame({"n": range(10)}).to_csv(path, index=False)

    profile = profile_dataset(path, sample_rows=100)

    assert profile["sampled"] is False
    assert "sampling_note" not in profile
    assert profile["shape"]["total_rows"] == 10


def test_output_stays_small_for_a_big_wide_file(tmp_path):
    """The end-to-end promise: cheaper than pasting the data."""
    path = tmp_path / "huge.csv"
    pd.DataFrame({f"c{i}": range(5_000) for i in range(60)}).to_csv(path, index=False)

    rendered = profile_to_json(profile_dataset(path))

    assert len(rendered) < 60_000
    assert len(rendered) * 20 < path.stat().st_size


# --- serialisation and path safety ----------------------------------------


def test_profile_is_valid_json_despite_nan(tmp_path):
    """NaN/Inf must not leak through; JSON has no way to spell them."""
    path = tmp_path / "nan.csv"
    pd.DataFrame({"v": [1.0, None, float("inf")], "only": [None, None, None]}).to_csv(
        path, index=False
    )

    # allow_nan=False makes this raise rather than emit invalid JSON.
    reloaded = json.loads(profile_to_json(profile_dataset(path)))

    assert reloaded["shape"]["rows_profiled"] == 3


def test_root_allows_paths_inside(tmp_path):
    path = tmp_path / "ok.csv"
    pd.DataFrame({"a": [1]}).to_csv(path, index=False)
    assert profile_dataset(path, root=tmp_path)["shape"]["rows_profiled"] == 1


def test_root_blocks_paths_outside(tmp_path):
    outside = tmp_path / "secret.csv"
    pd.DataFrame({"a": [1]}).to_csv(outside, index=False)
    allowed = tmp_path / "allowed"
    allowed.mkdir()

    with pytest.raises(ProfileError, match="outside the allowed root"):
        profile_dataset(outside, root=allowed)


def test_root_blocks_traversal_escape(tmp_path):
    """`..` must not be usable to climb out of the root."""
    outside = tmp_path / "secret.csv"
    pd.DataFrame({"a": [1]}).to_csv(outside, index=False)
    allowed = tmp_path / "allowed"
    allowed.mkdir()

    with pytest.raises(ProfileError, match="outside the allowed root"):
        profile_dataset(allowed / ".." / "secret.csv", root=allowed)


# --- delimiter and encoding handling ---------------------------------------


def test_semicolon_delimited_csv(tmp_path):
    """European open data is usually semicolon-separated."""
    path = tmp_path / "eu.csv"
    path.write_text(
        "Date;Station;Delay\n2024-01;Paris;3.5\n2024-02;Lyon;4.1\n", encoding="utf-8"
    )

    profile = profile_dataset(path)

    assert profile["shape"]["columns"] == 3
    assert [c["name"] for c in profile["columns"]] == ["Date", "Station", "Delay"]


def test_pipe_delimited_csv(tmp_path):
    path = tmp_path / "piped.csv"
    path.write_text("a|b|c\n1|2|3\n4|5|6\n", encoding="utf-8")

    assert profile_dataset(path)["shape"]["columns"] == 3


def test_bom_is_stripped_from_first_column_name(tmp_path):
    """Excel and public data portals emit a BOM; it must not enter the name."""
    path = tmp_path / "bom.csv"
    path.write_text("﻿Date;Value\n2024-01;1\n", encoding="utf-8")

    first = profile_dataset(path)["columns"][0]["name"]

    assert first == "Date"
    assert not first.startswith("﻿")


def test_header_word_is_not_split_on_a_letter(tmp_path):
    """Regression: a naive sniffer split the header "letter" on its "t"."""
    path = tmp_path / "single.csv"
    pd.DataFrame({"letter": list("abcdefghij")}).to_csv(path, index=False)

    profile = profile_dataset(path)

    assert profile["shape"]["columns"] == 1
    assert profile["columns"][0]["name"] == "letter"


def test_quoted_commas_do_not_break_comma_detection(tmp_path):
    """A comma inside a quoted field must not change the delimiter choice."""
    path = tmp_path / "quoted.csv"
    path.write_text(
        'id,note\n1,"hello, world"\n2,"another, one"\n3,"third, note"\n',
        encoding="utf-8",
    )

    profile = profile_dataset(path)

    assert [c["name"] for c in profile["columns"]] == ["id", "note"]
    assert profile["shape"]["rows_profiled"] == 3


# --- other formats ---------------------------------------------------------


def test_parquet_roundtrip(tmp_path):
    path = tmp_path / "d.parquet"
    pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]}).to_parquet(path, index=False)

    profile = profile_dataset(path)

    assert profile["file"]["format"] == "parquet"
    assert profile["shape"]["rows_profiled"] == 3


def test_jsonl_roundtrip(tmp_path):
    path = tmp_path / "d.jsonl"
    path.write_text('{"a": 1}\n{"a": 2}\n', encoding="utf-8")

    profile = profile_dataset(path)

    assert profile["file"]["format"] == "jsonl"
    assert profile["shape"]["rows_profiled"] == 2


def test_datetime_column_reports_range(tmp_path):
    path = tmp_path / "dates.parquet"
    pd.DataFrame({"when": pd.to_datetime(["2024-01-01", "2024-06-01"])}).to_parquet(
        path, index=False
    )

    stats = _column(profile_dataset(path), "when")["stats"]

    assert stats["min"].startswith("2024-01-01")
    assert stats["max"].startswith("2024-06-01")

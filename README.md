# mcp-data-profiler

An [MCP](https://modelcontextprotocol.io) server that lets an AI agent **understand a dataset without reading it**.

Point it at a CSV, Parquet, JSON, or Excel file and it returns a compact structured profile — types, ranges, missing values, and likely data-quality problems — instead of raw rows.

## The problem

To let an agent reason about a data file, you normally paste rows into the conversation. That is expensive, truncates on anything large, and still leaves the model guessing at column types and null rates.

A 5,000-row CSV is ~240,000 characters of raw rows. The profile of that same file is **2,391 characters** — 100× smaller — and answers more:

```
you:  what's in data/orders.csv?
       └─ profile_dataset(path="data/orders.csv")

5,000 rows × 6 columns, no duplicate rows.

  order_id         str      5000 distinct   ⚠ looks like an ID
  customer_region  str      4 values        AMER 1272, APAC 1257, EMEA 1250
  amount_eur       float64  2.00–1369.65    median 204.44
  currency         str      1 value         ⚠ constant ("EUR")
  ordered_at       str      5000 distinct   ⚠ dates stored as text
  notes            float64  —               ⚠ entirely null
```

Three real problems surfaced before any analysis started: a column that never varies, one that is completely empty, and a date column that will sort as text — so `"2024-10-01" < "2024-9-01"` — silently corrupting any time-based result.

## Install

Requires Python 3.10+.

```bash
pip install git+https://github.com/Ridadata/mcp-data-profiler.git
```

### Claude Code

```bash
claude mcp add data-profiler -- mcp-data-profiler
```

### Claude Desktop / other MCP clients

Add to your client's MCP config:

```json
{
  "mcpServers": {
    "data-profiler": {
      "command": "mcp-data-profiler"
    }
  }
}
```

To confine it to one directory, add `"args": ["--root", "/path/to/your/data"]`.

Then just ask about a file — *"profile data/orders.csv"*, *"what's wrong with this dataset?"*, *"which columns have missing values?"*

## The tool

### `profile_dataset(path, sample_rows=50000, max_columns=100, top_k=5)`

| Argument | Default | Meaning |
| --- | --- | --- |
| `path` | — | File to profile |
| `sample_rows` | `50000` | Rows to read. `null` reads everything (exact, slower) |
| `max_columns` | `100` | Cap on columns described, so wide tables stay small |
| `top_k` | `5` | Frequent values listed per categorical column |

**Formats:** `.csv` `.tsv` `.parquet` `.json` `.jsonl` `.ndjson` `.xlsx` `.xls`

**Per column:** dtype · null count and % · distinct count · sample values · min/max/mean/std/quartiles for numbers · min/max for dates · top values for categories

**Flags raised:**

| Flag | Meaning |
| --- | --- |
| `all_null` | Column is entirely empty |
| `constant` | Only ever one value |
| `high_cardinality_possible_id` | Nearly all values distinct — an identifier, not a feature |
| `numeric_stored_as_text` | Numbers typed as strings; comparisons and sorting will be wrong |
| `date_stored_as_text` | Dates typed as strings; same problem |
| `mixed_types` | One column holding several unrelated Python types |

### Example output

Real output, abbreviated:

```json
{
  "file": { "name": "orders.csv", "format": "csv", "size_bytes": 239846 },
  "shape": { "rows_profiled": 5000, "total_rows": 5000, "columns": 6 },
  "sampled": false,
  "columns": [
    {
      "name": "order_id",
      "dtype": "str",
      "null_count": 0,
      "null_pct": 0.0,
      "unique_count": 5000,
      "sample_values": ["ORD-000000", "ORD-000001", "ORD-000002"],
      "flags": ["high_cardinality_possible_id"]
    },
    {
      "name": "amount_eur",
      "dtype": "float64",
      "null_count": 0,
      "null_pct": 0.0,
      "unique_count": 4755,
      "stats": {
        "min": 2.0, "max": 1369.65, "mean": 244.54278, "std": 170.805364,
        "q25": 118.98, "median": 204.435, "q75": 331.065
      }
    },
    {
      "name": "currency",
      "dtype": "str",
      "unique_count": 1,
      "top_values": [{ "value": "EUR", "count": 5000 }],
      "flags": ["constant"]
    }
  ],
  "duplicate_rows": 0
}
```

## Design notes

**Bounded output.** The point is to cost less than the data itself, so the response is capped regardless of input width, and long strings are truncated. Near-unique columns skip the frequent-values list, since every count would be 1.

**Honest sampling.** Large files are profiled from a sample, but the result always carries `"sampled": true` and the true row count — a silently sampled statistic is a wrong statistic. Row counts come from Parquet metadata or a newline scan, never a full read.

**Path safety.** `--root` confines profiling to one directory. Paths are canonicalised first, so `..` and symlinks cannot escape.

## Limitations

- **Read-only, local files only.** No databases, no URLs, no writes.
- **Sampled by default.** Statistics reflect the first 50,000 rows unless you pass `sample_rows=null`.
- **Row-oriented.** No cross-column correlations, outlier detection, or plots.
- **pandas parsing rules apply.** The profile shows what pandas sees, which is what your own code will see. Notably, `"NA"`, `"N/A"`, and `"None"` are read as *missing*, so a region column containing `"NA"` for North America will report nulls. That is a real trap worth knowing about, and this tool surfaces it rather than hiding it.
- **Nested JSON** is not flattened; unhashable cells make the duplicate check inapplicable (reported as `null`).

## Development

```bash
git clone https://github.com/Ridadata/mcp-data-profiler.git
cd mcp-data-profiler
pip install -e ".[dev]"
pytest
```

`profiler.py` holds all logic and imports nothing from MCP, so it is testable directly and usable as a plain library:

```python
from mcp_data_profiler import profile_dataset
profile_dataset("data.csv")
```

`server.py` is only the MCP adapter.

Issues and PRs welcome.

## License

MIT

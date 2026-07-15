# Technical Decisions of the ETL — ARC-AGI

**Project:** Atlas | Arc Failure  
**Module:** Base Ingestion Pipeline (`main.py`)  
**Pipeline version:** 1.1.0  
**Author:** William Emmanuel Fernández Castillo  
**Date:** June 12, 2026  

> This document records the design decisions made during the construction
> of the base ETL. Each decision describes the problem it solves, the alternatives
> considered, and the justification for the final choice.

---

## Decision 1 — How to handle nested matrices

### Context

Each ARC-AGI task is represented as a 2D integer matrix (grid).
For example, a 3x3 grid in the raw JSON has this structure:

```json
"input": [
  [0, 1, 2],
  [3, 4, 5],
  [6, 7, 8]
]

```

The problem is that a columnar database like Parquet does not natively support
variable-sized arrays within a cell. We needed a storage strategy that would not
lose structural information.

### Considered Alternatives

| Alternative | Description | Discarded because... |
| --- | --- | --- |
| `matriz.flatten()` only | Flatten to a 1D list | Loses spatial structure (rows, columns). Geometry cannot be reconstructed without knowing the shape beforehand |
| Columns `celda_0`, `celda_1`... | One column per cell | ARC grids have variable dimensions (from 1x1 to 30x30). This would generate up to 900 columns, mostly empty |
| Save only the JSON file reference | Do not store the grid, only the path | Makes every query dependent on the original file. Breaks the portability of the analytical database |

### Adopted Decision: Double serialization (`grid_2d` + `grid_flat`)

It was decided to save **two serialized representations** of each grid as JSON strings:

```python
"grid_2d":   json.dumps([[0,1,2],[3,4,5],[6,7,8]])  # → "[[0,1,2],[3,4,5],[6,7,8]]"
"grid_flat": json.dumps([0,1,2,3,4,5,6,7,8])        # → "[0,1,2,3,4,5,6,7,8]"

```

* **`grid_2d`** preserves the full spatial structure. It is necessary for analyzing geometric transformations (rotations, symmetries, translations), which are the core of the project.
* **`grid_flat`** is the linearized version. AI models consuming these data typically expect 1D input vectors.

To reconstruct the original matrix from Python, it is enough to:

```python
grid_original = json.loads(df['grid_2d'][0])

```

Additionally, a `grid_hash` (MD5) of each grid's content is stored.
This allows efficient comparison of input and output and the detection of
duplicated grids among the 400 real tasks without re-reading the files.

---

## Decision 2 — What data types to use

**Last updated:** June 29, 2026 (columns `example_id` and `source_path` added;
`transformation_type` and `ingested_at` justifications expanded).

### Context

A poorly designed type schema generates two concrete problems:
RAM memory waste when processing the 400 real files, and
incorrect results in analytical queries (for example, comparing
the string `"None"` against an actual `NULL` produces different results).

### Adopted Type Map

All 15 columns of the frozen tasks Parquet schema are listed below.
"Python type" is the type in the in-memory DataFrame before writing.
"Parquet type" is what PyArrow stores on disk.

| Field | Python type | Parquet type | Nullable | Justification |
| --- | --- | --- | --- | --- |
| `task_id` | `str` | `string` (partition key) | No | Derived from `Path.stem` of the source JSON. Kept as string even though the evaluation set uses hex names: treating it as an integer would lose leading zeros (e.g. `"00576224"` → `576224`). |
| `split` | `category` | `string` (partition key) | No | Only 2 values (`train` / `test`). Stored as a Hive partition key, so the value is encoded in the directory path, not repeated in every row of the Parquet file. In memory it is `category` to save RAM when loading the full dataset. |
| `example_id` | `int64` | `int64` | No | 1-based index of the example within its split, matching ARC paper convention. Using 1-based (not 0-based) avoids off-by-one confusion when cross-referencing against the raw JSON by hand. |
| `grid_role` | `category` | `dictionary` | No | Only 2 values (`input` / `output`). Parquet's `dictionary` encoding is the columnar equivalent of a categorical: it stores a lookup table once and uses integer codes per row, reducing file size significantly on large datasets. |
| `rows` | `int64` | `int64` | No | Number of rows in the grid. ARC range: 1–30. Integer arithmetic is used downstream for spatial analysis (e.g. aspect ratio, symmetry checks). |
| `cols` | `int64` | `int64` | No | Number of columns in the grid. Same reasoning as `rows`. Stored separately so queries like `WHERE rows = cols` (square grids) are trivial. |
| `grid_2d` | `str` | `string` | No | The full 2D matrix serialized as a JSON string (e.g. `"[[0,1],[2,3]]"`). Chosen over a native Parquet list-of-lists because variable-length nested arrays require Parquet's `LIST` type, which is poorly supported by DuckDB and Pandas without explicit schema declaration. Deserialize with `json.loads()`. |
| `grid_flat` | `str` | `string` | No | The same grid linearized to a 1D JSON string (e.g. `"[0,1,2,3]"`). Provided as a pre-computed convenience for inference code that feeds flat vectors to models. Avoids repeated `[val for row in grid for val in row]` at query time. |
| `grid_hash` | `str` | `string` | No | MD5 hex digest (32 characters) of the JSON-serialized grid content. MD5 was chosen over SHA-256 because the goal is deduplication and input/output comparison, not cryptographic security. MD5 is faster, deterministic, and universally supported. Fixed 32-char length allows efficient string indexing. |
| `n_colors` | `int64` | `int64` | No | Count of distinct color values present in the grid. ARC colors run 0–9, so the range is 1–10. Integer type is correct; there is no case where this value would be fractional. |
| `color_counts` | `str` | `string` | No | Per-color frequency stored as a JSON string (e.g. `{"0": 5, "3": 2}`). **Important:** Python's `json.dumps` always converts dictionary keys to strings, even if the original keys were integers. Downstream consumers must parse keys as integers if needed: `{int(k): v for k, v in json.loads(row).items()}`. |
| `transformation_type` | `None` | `string` (nullable) | Yes | Intentionally `NULL` at ingestion. ARC-AGI does not label transformation types in the raw data — classifying them (rotation, symmetry, color substitution, etc.) is the responsibility of the analysis module. Stored as a nullable `string` (not a dedicated enum) so the analysis module can write free-form labels without a schema change. |
| `source_path` | `str` | `string` | No | Repo-relative path to the source JSON at ingestion time, normalized to POSIX forward slashes via `_source_path_for_row()` (e.g. `data/raw/evaluation/00576224.json` on all platforms). Required by `agent_context/conventions/schema_contracts.md` for end-to-end traceability: given any row in the Parquet, you can locate the exact file that produced it without querying a separate registry. |
| `pipeline_version` | `str` | `string` | No | Semantic version of the ETL that produced the row (e.g. `"1.1.0"`). Allows filtering rows by ETL version if a bug is found and only a subset of rows need to be reprocessed. Format is `MAJOR.MINOR.PATCH`; the value is the constant `PIPELINE_VERSION` in `main.py`. |
| `ingested_at` | `str` ISO 8601 | `string` | No | UTC timestamp derived from the **source file's modification time** (`Path.stat().st_mtime`), not from `datetime.now()`. This guarantees that re-running the ETL on the same input produces the exact same value in this field, which is the key condition for bit-identical Parquet output. Format: `2026-06-09T14:32:00+00:00`. Stored as string rather than a Parquet `TIMESTAMP` type to avoid timezone encoding ambiguity across PyArrow versions. |

### Why no `float` columns?

The tasks Parquet contains no floating-point values by design.
ARC grids use integer color codes (0–9). Dimensions (`rows`, `cols`) and
counts (`n_colors`) are integers. Timestamps and hashes are strings.
Float columns belong in the inference results Parquet (e.g. `cost_usd`,
`latency_ms`), not in the normalized task representation.

### Why no native list or array columns?

Parquet supports nested `LIST` types, but their behavior is inconsistent
across engines: DuckDB requires explicit schema hints, Pandas needs
`ArrowDtype` or manual reconstruction, and PyArrow's inference sometimes
produces `large_list` instead of `list`. Serializing grids as JSON strings
trades a small deserialization step for full engine compatibility and
zero schema negotiation overhead.

---

## Decision 3 — How to separate train and test

### Context

Each ARC-AGI JSON file has two sections:

```json
{
  "train": [ { "input": [...], "output": [...] }, ... ],
  "test":  [ { "input": [...] } ]
}

```

The most important structural difference is that **the `test` examples
do not have an output in the real data**: that output is the answer
the model is asked to predict. Treating both splits identically
produces silent errors when moving from `dummy_task.json` to the 400
real tasks.

### Considered Alternatives

| Alternative | Description | Discarded because... |
| --- | --- | --- |
| Two separate Parquet tables (`train.parquet` / `test.parquet`) | One file per split | Complicates joins and comparisons. Duplicates query logic |
| Filter and discard test | Do not process the test split | Loses valuable information: the test input is necessary to send the prompt to the model |
| Throw error if test has no output | Reject as malformed | Incorrect by design of the benchmark. In ARC, a test without output is the normal case, not an exception |

### Adopted Decision: `split` column + conditional validation

Two complementary mechanisms were adopted:

**1. `split` column in each row.** Each record carries its explicit origin:

```text
task_id  | split | example_id | grid_role | ...
task_001 | train | 1          | input     | ...
task_001 | train | 1          | output    | ...
task_001 | test  | 1          | input     | ...   ← without output row (this is correct)

```

This allows filtering with a single query without reopening files:

```python
df_train = df[df['split'] == 'train']
df_test  = df[df['split'] == 'test']

```

**2. Conditional validation of the output based on the split.** The validator treats
`output = None` as valid only in the `test` split:

```python
# In validar_grid():
if grid is None and role == "output" and split == "test":
    return True, ""   # Valid: test without output is normal in ARC

```

If a `train` example has no output, it is indeed logged
as an error in `{task_id}_errores.parquet`, because that case indicates a corrupted file.

---

## Decision 4 — Partitioning strategy: `split` → `task_id`

**Date:** June 29, 2026

### Context

The Parquet dataset must support two distinct access patterns efficiently:
1. Load all examples of a given split (e.g. "give me every test input") for
   batch inference.
2. Load all examples of a single task (e.g. "give me task `00576224` train + test")
   for prompt construction.

### Considered Alternatives

| Alternative | Description | Discarded because... |
| --- | --- | --- |
| Single flat file | One `evaluation.parquet` | No predicate pushdown. Every query loads all 400 tasks |
| Partition by `task_id` only | One directory per task | Querying all train inputs requires opening 400 directories |
| Partition by `split` only | One directory per split | A single task spans two directories; no cheap single-task load |
| Partition by `task_id` → `split` | task first, then split | Reverses the most common access order: batch inference filters by split first, not by task |

### Adopted Decision: Hive partition `split=<value>/task_id=<value>/`

```
data/parquet/evaluation/
  split=train/
    task_id=00576224/part-0.parquet   ← all train rows for this task
    task_id=009d5c81/part-0.parquet
    ...
  split=test/
    task_id=00576224/part-0.parquet   ← all test rows for this task
    ...
```

- Batch inference reads `split=test/` and skips all train directories entirely
  (partition pruning at the filesystem level).
- Prompt construction reads both `split=train/task_id=X/` and
  `split=test/task_id=X/` — two directory reads instead of a full scan.
- With ~400 tasks the total number of leaf directories (~800) stays well within
  what DuckDB, PyArrow, and Pandas handle without performance degradation.

**Caveat for consumers:** A single task's rows live in two separate directories.
Always load the full dataset and filter in memory, or read both partition paths
explicitly. See `notebooks/inference_input_reader.py` for a reference
implementation.

---

## Decision 5 — Schema freeze and enforcement

**Date:** June 29, 2026

### Context

Starting the week of June 29, 2026, the team agreed that column changes to the
tasks Parquet require explicit approval before merging. Without an automated
guard, a developer could add a column, break downstream consumers, and only
discover the problem after inference runs had already started.

### Adopted Decision: `TASKS_PARQUET_SCHEMA` constant + `validate_output_schema()`

The frozen schema is declared as a constant dictionary in `main.py`:

```python
TASKS_PARQUET_SCHEMA = {
    "task_id":             {"nullable": False},
    "split":               {"nullable": False},
    ...
    "transformation_type": {"nullable": True},
    ...
}
```

`validate_output_schema(df, schema)` runs **before** any Parquet write and raises
`ValueError` immediately if any of these conditions are detected:

1. **Extra column present** — someone added a column without updating the schema
   constant and getting approval.
2. **Required column missing** — a refactor silently dropped a field.
3. **NULL in a non-nullable column** — a code path left a mandatory field empty.

The check is strict by design: it is easier to approve a legitimate addition than
to debug a silent schema drift that only surfaces in a downstream query.

**To add a column legitimately:**
1. Update `TASKS_PARQUET_SCHEMA` in `main.py`.
2. Update Decision 2 type map in this file.
3. Regenerate the Parquet and verify `validate_output_schema` passes.
4. Get team approval before merging.

---

## Decision 6 — Reproducibility: `ingested_at` from file mtime

**Date:** June 29, 2026

### Context

The requirement is that deleting and regenerating the Parquet from the same
source JSON files must produce **bit-identical output**. This is necessary for
diffing, auditing, and trusting that a regenerated dataset is equivalent to the
original.

The original implementation used `datetime.now(timezone.utc)` for `ingested_at`,
which changes on every run and makes two otherwise identical runs produce
different Parquet files.

### Considered Alternatives

| Alternative | Description | Discarded because... |
| --- | --- | --- |
| Keep `datetime.now()` | Timestamp of the ETL run | Changes every run; breaks bit-identical regeneration |
| Remove `ingested_at` entirely | No timestamp in the row | Loses traceability: you cannot tell when the source data was current |
| Store as Parquet file metadata | Embed in file header, not a column | Parquet metadata is not queryable with standard SQL; DuckDB ignores it by default |
| Hardcode a fixed timestamp | Always use `"2026-01-01T00:00:00Z"` | Misleading; does not reflect when the source was actually last modified |

### Adopted Decision: `Path.stat().st_mtime` converted to UTC ISO 8601

```python
file_mtime = datetime.fromtimestamp(
    file_path.stat().st_mtime, tz=timezone.utc
).isoformat()
```

This timestamp reflects **when the source JSON file was last modified**, which
is stable as long as the input does not change. If a task file is updated (e.g.
ARC-AGI releases a corrected version), the mtime changes and so does
`ingested_at`, which correctly signals that this row comes from a newer version
of the source.

**Verified:** Two consecutive runs on the same 5 evaluation files produced
bit-identical MD5 hashes for all 10 Parquet partition files.

---

## Decision 7 — Quality log: dual output (Parquet + text file)

**Date:** June 29, 2026

### Context

When a grid fails validation, the pipeline needs to record the failure in a way
that serves two audiences simultaneously:

- **Developers running the ETL locally** need to see failures immediately in the
  terminal without opening a file.
- **Data analysts and auditors** need a queryable, structured record of all
  rejected grids across a full batch run.

### Adopted Decision: write to both `logs/quality_<timestamp>.log` and `data/parquet/evaluation_errors/`

**Text log (`logs/quality_<timestamp>.log`):**
- Written by a dedicated Python logger (`arc.quality`) with a `FileHandler` at
  `WARNING` level.
- Human-readable, one line per rejected grid.
- Timestamped per run (not overwritten) so the full rejection history is
  preserved across multiple ETL executions.
- Only captures quality warnings — not pipeline INFO events — so the file stays
  focused and grep-friendly.

**Parquet error table (`data/parquet/evaluation_errors/`):**
- Same Hive partitioning as the valid data (`split` → `task_id`).
- Schema: `task_id`, `split`, `example_id`, `grid_role`, `error`, `source_path`,
  `ingested_at`.
- Queryable with DuckDB or Pandas. Enables aggregate analysis:
  "how many tasks had dimension errors vs null errors across the full evaluation
  set?"

The two outputs are complementary, not redundant: the text log is for immediate
human inspection; the Parquet table is for programmatic analysis.

---

## Deferred Fields (next sprint)

The following fields were identified as necessary for the model inference
module, but fall outside the scope of the base ETL.
They are documented here so the schema contemplates them from the design phase:

| Field | Purpose |
| --- | --- |
| `modelo_id` | Identifier of the evaluated model (e.g., `"gpt-4o"`, `"ollama-llama3"`) |
| `prompt_version` | Version of the prompt template used |
| `latencia_ms` | Model response time in milliseconds |
| `costo` | Cost in USD of the API call |
| `correcto` | Boolean: does the predicted output match the expected one? |
| `intento` | Attempt number (for retry or multi-sample strategies) |
| `task_version` | ARC task file version (in case the benchmark is updated) |
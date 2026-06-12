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

### Context

A poorly designed type schema generates two concrete problems:
RAM memory waste when processing the 400 real files, and
incorrect results in analytical queries (for example, comparing
the string `"None"` against an actual `NULL` produces different results).

### Adopted Type Map

| Field | Python Type | Parquet Type | Justification |
| --- | --- | --- | --- |
| `task_id` | `str` | `string` | Derived from the file name (`Path.stem`). Never numeric to avoid collisions |
| `split` | `category` | `dictionary` | Only 2 possible values (`train`/`test`). Categorical saves memory in large datasets |
| `grid_role` | `category` | `dictionary` | Only 2 possible values (`input`/`output`). Same reasoning as `split` |
| `rows` / `cols` | `int` | `int64` | Integer dimensions. In ARC the range is 1–30 |
| `grid_2d` / `grid_flat` | `str` | `string` | Serialized JSON. Portable and without external dependencies to deserialize |
| `grid_hash` | `str` | `string` | Hexadecimal MD5 (32 characters). Fixed length, requires no special type |
| `n_colors` | `int` | `int64` | Count of unique colors. Real range: 1–10 (ARC colors 0 to 9) |
| `color_counts` | `str` | `string` | Dictionary serialized as JSON. Format: `{"0": 5, "3": 2, ...}` |
| `transformation_type` | `None` → `NULL` | `null` | Reserved field. Python's `None` (not the string `"None"`) is used so Parquet registers it as an actual null and queries with `IS NULL` work correctly |
| `pipeline_version` | `str` | `string` | Semver (`"1.1.0"`). Allows tracking which ETL version generated each row |
| `ingested_at` | `str` ISO 8601 | `string` | UTC timestamp in standard format. Example: `2026-06-09T14:32:00+00:00` |

### Note on `transformation_type`

This field is intentionally left as `NULL` in this version of the ETL.
In ARC-AGI, the classification of the transformation type (rotation, symmetry,
color change, etc.) **is not labeled in the raw data**: it is
precisely what the models must discover. Classifying transformations
is the responsibility of the analysis module, not the ingestion ETL.

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

```

```
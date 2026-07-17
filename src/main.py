import argparse
import json
import hashlib
import logging
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter

import config
from benchmark_packs import (
    BenchmarkPackError,
    attach_benchmark_columns,
    count_task_files,
    format_pack_list,
    legacy_pack,
    require_tasks_dir,
    resolve_pack,
    write_pack_sidecar,
)

# LOGGING CONFIGURATION
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s'
)

# Dedicated quality logger — writes only validation failures to a text file.
# Pipeline operational logs (INFO) stay on the console via the root logger.
# This logger is configured at runtime in __main__ once the log path is known.
quality_logger = logging.getLogger("arc.quality")

# PIPELINE CONSTANTS
PROJECT_ROOT     = Path(__file__).resolve().parent.parent
PIPELINE_VERSION = "1.2.0"  # + benchmark pack metadata columns (Decision 20)
VALID_SPLITS     = ["train", "test"]
VALID_ROLES      = ["input", "output"]
ARC_COLOR_MIN    = 0
ARC_COLOR_MAX    = 9

# FROZEN SCHEMA — tasks Parquet (effective from 2026-06-29; pack cols 2026-07-15)
# Adding, removing, or renaming columns requires team approval.
# nullable=True means the column may contain NULL values by design.
TASKS_PARQUET_SCHEMA = {
    "task_id":             {"nullable": False},
    "split":               {"nullable": False},
    "example_id":          {"nullable": False},
    "grid_role":           {"nullable": False},
    "rows":                {"nullable": False},
    "cols":                {"nullable": False},
    "grid_2d":             {"nullable": False},
    "grid_flat":           {"nullable": False},
    "grid_hash":           {"nullable": False},
    "n_colors":            {"nullable": False},
    "color_counts":        {"nullable": False},
    "transformation_type": {"nullable": True},   # filled by analysis module
    "source_path":         {"nullable": False},
    "pipeline_version":    {"nullable": False},
    "ingested_at":         {"nullable": False},
    # Benchmark pack pin (Decision 20) — always stamped (legacy_raw_dir when
    # ETL runs without --benchmark-pack).
    "pack_id":             {"nullable": False},
    "benchmark_family":    {"nullable": False},
    "benchmark_name":      {"nullable": False},
    "benchmark_version":   {"nullable": False},
    "split_name":          {"nullable": False},  # pack-level, not train/test
    "task_source":         {"nullable": False},
}

# ARCHITECTURE NOTE
# Benchmark pack pinning lives in TASKS_PARQUET_SCHEMA (Decision 20).
# Inference/evaluation fields live in contracts.EVALUATION_RESULTS_SCHEMA.

# EXTRACTION

def extract_json_data(file_path: Path) -> dict:
    """
    Opens the JSON and converts it into a Python dictionary.
    Handles the two most common errors: missing file and malformed JSON.
    """
    logging.info(f"Reading file: {file_path}")
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            return json.load(file)
    except FileNotFoundError:
        logging.error(f"File not found: {file_path}")
        raise
    except json.JSONDecodeError as e:
        logging.error(f"Invalid JSON in '{file_path}': {e}")
        raise

# VALIDATION

def validate_grid(grid, role: str, split: str) -> tuple:
    """
    Validates the structure, consistency, and values of a grid.

    TECHNICAL DECISION — Train/test separation:
        In ARC-AGI, the 'test' split legitimately has no output
        (it is what the models must predict). Therefore, output=None
        in test is valid and is not logged as an error.

    Returns: (is_valid: bool, error_message: str)
    """
    # Special case: missing output in test is VALID in ARC
    if grid is None and role == "output" and split == "test":
        return True, ""

    if grid is None:
        return False, f"Grid '{role}' is None in split='{split}' (content expected)"

    if not isinstance(grid, list) or len(grid) == 0:
        return False, f"Grid '{role}' is not a list or is empty"

    if not isinstance(grid[0], list):
        return False, f"Grid '{role}' is not 2D (expected list of lists)"

    expected_cols = len(grid[0])
    for i, row in enumerate(grid):
        if not isinstance(row, list):
            return False, f"Row {i} in grid '{role}' is not a list"
        if len(row) != expected_cols:
            return False, (
                f"Grid '{role}' has inconsistent dimensions: "
                f"row {i} has {len(row)} cols, expected {expected_cols}"
            )
        for j, val in enumerate(row):
            if not isinstance(val, int) or not (ARC_COLOR_MIN <= val <= ARC_COLOR_MAX):
                return False, (
                    f"Value out of ARC range [{ARC_COLOR_MIN}-{ARC_COLOR_MAX}] "
                    f"in grid '{role}', position [{i}][{j}]: {val}"
                )

    return True, ""


# METADATA CALCULATION

def calculate_grid_metadata(grid: list) -> dict:
    """
    Derives analytical metadata from a valid 2D grid.

    TECHNICAL DECISION — Why save grid_flat and grid_2d:
        - grid_2d: preserves the spatial structure for analysis of
          geometric transformations (rotations, symmetries, etc.).
        - grid_flat: linearized version useful for embeddings and models
          that consume input vectors.
        - grid_hash: digital fingerprint of the grid to detect duplicates
          and compare input vs output efficiently.

    TECHNICAL DECISION — Data types:
        ARC values are integers from 0-9 (colors). They are stored
        as standard Python int; PyArrow will infer them as int64
        when writing the Parquet.
    """
    rows = len(grid)
    cols = len(grid[0])

    # Flatten the grid for operations requiring a 1D vector
    flat_grid = [val for row in grid for val in row]

    # MD5 hash of the serialized content (reproducible and portable)
    content_bytes = json.dumps(grid, separators=(',', ':')).encode('utf-8')
    grid_hash = hashlib.md5(content_bytes).hexdigest()

    # Color distribution: how many times each value (0-9) appears
    color_counts = dict(Counter(flat_grid))
    n_colors     = len(color_counts)

    return {
        "rows":         rows,
        "cols":         cols,
        "grid_2d":      json.dumps(grid),         # 2D matrix serialized
        "grid_flat":    json.dumps(flat_grid),    # Flattened version serialized
        "grid_hash":    grid_hash,
        "n_colors":     n_colors,
        "color_counts": json.dumps(color_counts),
    }


# TRANSFORMATION (orchestrates validation plus metadata)

def transform_task_to_rows(
    task_json: dict,
    task_id: str,
    source_path: str = "",
    ingested_at: str = "",
) -> tuple:
    """
    Converts an ARC task JSON into a LONG tabular format.

    TECHNICAL DECISION — Long format (one row per grid):
        Instead of having grid_input and grid_output as separate
        columns, each grid occupies its own row with a field
        'grid_role' = 'input' | 'output'.
        This greatly facilitates aggregations, comparisons, and later joins
        without the need to restructure the schema.

    Output schema:
        task_id, split, example_id, grid_role,
        rows, cols, grid_2d, grid_flat, grid_hash,
        n_colors, color_counts, transformation_type,
        source_path, pipeline_version, ingested_at

    Returns: (valid_df, error_df)
        - valid_df: clean rows ready for analysis
        - error_df: record of rejected grids for auditing
    """
    logging.info(f"[{task_id}] Starting transformation...")
    valid_rows = []
    error_rows = []
    # REPRODUCIBILITY: ingested_at is derived from the source file's mtime so
    # deleting and regenerating the Parquet produces bit-identical rows.
    # datetime.now() would change every run and break downstream diffing.
    if not ingested_at:
        ingested_at = datetime.now(timezone.utc).isoformat()

    for split in VALID_SPLITS:
        if split not in task_json:
            logging.warning(f"[{task_id}] Split '{split}' missing in JSON.")
            continue

        for example_id, example in enumerate(task_json[split], start=1):
            for role in VALID_ROLES:

                grid = example.get(role, None)

                # Validation
                is_valid, error_message = validate_grid(grid, role, split)

                if not is_valid:
                    msg = (
                        f"[{task_id}] Grid rejected → "
                        f"split={split}, example={example_id}, role={role}: {error_message}"
                    )
                    logging.warning(msg)
                    quality_logger.warning(msg)
                    error_rows.append({
                        "task_id":     task_id,
                        "split":       split,
                        "example_id":  example_id,
                        "grid_role":   role,
                        "error":       error_message,
                        "source_path": source_path,
                        "ingested_at": ingested_at,
                    })
                    continue

                # Output None in test is valid, but doesn't generate a row
                if grid is None:
                    continue

                # Metadata plus row construction
                metadata = calculate_grid_metadata(grid)

                valid_rows.append({
                    "task_id":             task_id,
                    "split":               split,
                    "example_id":          example_id,
                    "grid_role":           role,
                    **metadata,
                    "transformation_type": None,  # Will be inferred in analysis module
                    "source_path":         source_path,
                    "pipeline_version":    PIPELINE_VERSION,
                    "ingested_at":         ingested_at,
                })

    # DataFrames construction
    valid_df = pd.DataFrame(valid_rows)
    error_df = pd.DataFrame(error_rows)

    # Memory optimization: low cardinality columns to categorical
    if not valid_df.empty:
        for col in ["split", "grid_role"]:
            valid_df[col] = valid_df[col].astype('category')

    logging.info(
        f"[{task_id}] Transformation completed: "
        f"{len(valid_df)} valid rows, {len(error_df)} errors."
    )
    return valid_df, error_df


# SCHEMA VALIDATION

def validate_output_schema(dataframe: pd.DataFrame, schema: dict) -> None:
    """
    Enforces the frozen Parquet schema before any write operation.
    Raises ValueError immediately so bad data never reaches disk.

    Checks:
      1. No unexpected columns (strict — additions require approval).
      2. No missing columns.
      3. Non-nullable columns contain no NULL values.
    """
    expected = set(schema.keys())
    actual   = set(dataframe.columns)

    extra   = actual - expected
    missing = expected - actual

    errors = []
    if extra:
        errors.append(f"Unexpected columns (need approval to add): {sorted(extra)}")
    if missing:
        errors.append(f"Missing columns: {sorted(missing)}")

    if errors:
        raise ValueError("Schema violation:\n" + "\n".join(f"  - {e}" for e in errors))

    for col, rules in schema.items():
        if col not in dataframe.columns:
            continue
        if not rules["nullable"] and dataframe[col].isnull().any():
            null_count = dataframe[col].isnull().sum()
            errors.append(f"Column '{col}' is non-nullable but has {null_count} NULL(s)")

    if errors:
        raise ValueError("Schema violation:\n" + "\n".join(f"  - {e}" for e in errors))

    logging.info("Schema validation passed (%d columns, %d rows).", len(actual), len(dataframe))


# STORAGE

def save_as_parquet(dataframe: pd.DataFrame, output_path: Path, label: str = "data") -> None:
    """
    Saves the DataFrame in Parquet format with PyArrow.
    - Creates the output directory if it doesn't exist.
    - Writes nothing if the DataFrame is empty (avoids ghost files).
    """
    if dataframe.empty:
        logging.warning(f"DataFrame '{label}' empty → no file will be written at {output_path}")
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    dataframe.to_parquet(output_path, engine='pyarrow', index=False)
    logging.info(f"[{label}] Saved: {output_path} ({len(dataframe)} rows)")


def save_partitioned_parquet(
    dataframe: pd.DataFrame,
    output_dir: Path,
    partition_cols: list,
    label: str = "data",
) -> None:
    """
    Writes a Hive-partitioned Parquet dataset (one sub-directory per partition key).

    TECHNICAL DECISION — Hive partitioning layout:
        Partition columns are encoded in the directory path, e.g.:
            split=train/task_id=00576224/part-0.parquet
        This makes the dataset natively readable by DuckDB, PyArrow, and Pandas
        without any custom logic, and enables efficient predicate pushdown when
        querying a single split or task.

    Categorical columns in partition_cols are cast to str before writing because
    pandas to_parquet does not accept categorical types as partition keys.
    """
    if dataframe.empty:
        logging.warning(f"DataFrame '{label}' empty → no partition will be written to {output_dir}")
        return

    df_out = dataframe.copy()
    for col in partition_cols:
        if col in df_out.columns:
            df_out[col] = df_out[col].astype(str)

    output_dir.mkdir(parents=True, exist_ok=True)
    df_out.to_parquet(
        output_dir,
        engine='pyarrow',
        index=False,
        partition_cols=partition_cols,
    )
    logging.info(
        f"[{label}] Partitioned Parquet written → {output_dir} "
        f"| partitions: {partition_cols} | rows: {len(dataframe)}"
    )


# BATCH INGESTION

def _source_path_for_row(file_path: Path) -> str:
    """Relative repo path with POSIX slashes — stable across OS and CI."""
    resolved = file_path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def process_folder(input_dir: Path) -> tuple:
    """
    Reads every *.json file in input_dir and runs the full ETL on each one.

    Returns: (combined_valid_df, combined_error_df)
        Both DataFrames span all tasks; task_id distinguishes the source.
    """
    json_files = sorted(input_dir.glob("*.json"))
    if not json_files:
        logging.warning(f"No JSON files found in: {input_dir}")
        return pd.DataFrame(), pd.DataFrame()

    logging.info(f"Found {len(json_files)} JSON file(s) in {input_dir}")

    valid_frames = []
    error_frames = []

    for file_path in json_files:
        task_id = file_path.stem
        try:
            raw_data    = extract_json_data(file_path)
            file_mtime  = datetime.fromtimestamp(
                file_path.stat().st_mtime, tz=timezone.utc
            ).isoformat()
            valid_df, error_df = transform_task_to_rows(
                raw_data,
                task_id=task_id,
                source_path=_source_path_for_row(file_path),
                ingested_at=file_mtime,
            )
            if not valid_df.empty:
                valid_frames.append(valid_df)
            if not error_df.empty:
                error_frames.append(error_df)
        except Exception as exc:
            msg = f"[{task_id}] Skipped due to error: {exc}"
            logging.error(msg)
            quality_logger.error(msg)

    combined_valid  = pd.concat(valid_frames,  ignore_index=True) if valid_frames  else pd.DataFrame()
    combined_errors = pd.concat(error_frames, ignore_index=True) if error_frames else pd.DataFrame()

    logging.info(
        f"Batch complete: {len(json_files)} files | "
        f"{len(combined_valid)} valid rows | {len(combined_errors)} error rows"
    )
    return combined_valid, combined_errors


def _warn_if_corpus_mixes_packs(output_dir: Path, current_pack_id: str) -> None:
    """Warn when Hive partitions retain task rows from more than one pack.

    ETL writes/overwrites by task_id but does not delete other packs' tasks.
    The sidecar always reflects the last pack processed.
    """
    parts = list(output_dir.glob("split=*/task_id=*/*.parquet"))
    if not parts:
        return
    packs: set[str] = set()
    for part in parts:
        try:
            chunk = pd.read_parquet(part, columns=["pack_id"])
        except (OSError, ValueError, KeyError):
            continue
        if "pack_id" not in chunk.columns or chunk.empty:
            continue
        packs.update(chunk["pack_id"].dropna().astype(str).unique())
        if len(packs) > 1:
            break
    if len(packs) <= 1:
        return
    logging.warning(
        "Evaluation corpus at %s contains task rows from multiple packs (%s). "
        "ETL accumulates by task_id; _benchmark_pack.json reflects only the "
        "LAST pack processed (%s). Re-run "
        "`python src/main.py --benchmark-pack <target>` before a real "
        "evaluation, or isolate corpora with --output-root.",
        output_dir, ", ".join(sorted(packs)), current_pack_id,
    )


# ENTRY POINT

def main() -> None:
    # Paths are cwd-relative BY DESIGN (the smoke test runs this module from
    # an isolated temp dir). Flag > ATLAS_OUTPUT_ROOT > default; with no flags
    # and no env vars the behavior is identical to earlier versions.
    parser = argparse.ArgumentParser(
        description="ARC-AGI base ETL: raw task JSON → validated, "
                    "Hive-partitioned tasks Parquet (frozen schema).",
    )
    parser.add_argument("--input-dir", type=Path, default=None,
                        help="directory of raw ARC task JSON files "
                             "(default: data/raw/evaluation, or the selected "
                             "pack's tasks_dir)")
    parser.add_argument("--benchmark-pack", default=None,
                        help="registered pack id under benchmark_packs/ "
                             f"(e.g. arc_agi_2; or ${config.ENV_BENCHMARK_PACK})")
    parser.add_argument("--benchmark-pack-path", type=Path, default=None,
                        help="path to a local pack root (directory with "
                             "manifest.json) or to the manifest file itself")
    parser.add_argument("--list-benchmark-packs", action="store_true",
                        help="print registered packs and exit")
    parser.add_argument("--output-root", type=Path, default=None,
                        help="root for evaluation/ and evaluation_errors/ "
                             f"(default: data/parquet, or ${config.ENV_OUTPUT_ROOT})")
    parser.add_argument("--log-dir", type=Path, default=Path("logs"),
                        help="quality-log directory (default: %(default)s)")
    args = parser.parse_args()

    if args.list_benchmark_packs:
        print(format_pack_list())
        raise SystemExit(0)

    try:
        output_root = args.output_root or config.output_root() or Path("data/parquet")
        pack_id = config.resolve(args.benchmark_pack, config.ENV_BENCHMARK_PACK)
    except config.ConfigError as exc:
        raise SystemExit(f"ERROR: {exc}")

    if args.benchmark_pack_path and pack_id:
        raise SystemExit(
            "ERROR: pass only one of --benchmark-pack / --benchmark-pack-path"
        )

    pack = None
    if args.benchmark_pack_path or pack_id:
        try:
            pack = resolve_pack(pack_id=pack_id, pack_path=args.benchmark_pack_path)
            input_dir = args.input_dir or require_tasks_dir(pack)
        except BenchmarkPackError as exc:
            raise SystemExit(f"ERROR: {exc}")
    else:
        input_dir = args.input_dir or Path("data/raw/evaluation")
        pack = legacy_pack(input_dir)

    output_dir = output_root / "evaluation"
    error_dir  = output_root / "evaluation_errors"
    log_dir    = args.log_dir

    # Quality log file — one file per run, timestamped to avoid overwriting history.
    log_dir.mkdir(parents=True, exist_ok=True)
    run_ts   = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = log_dir / f"quality_{run_ts}.log"
    _fh = logging.FileHandler(log_path, encoding="utf-8")
    _fh.setLevel(logging.WARNING)
    _fh.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    quality_logger.addHandler(_fh)
    quality_logger.setLevel(logging.WARNING)

    logging.info("=" * 60)
    logging.info(f"STARTING ARC-AGI ETL  |  pipeline_version={PIPELINE_VERSION}")
    logging.info(
        "benchmark pack     |  pack_id=%s  name=%s  version=%s",
        pack.pack_id, pack.benchmark_name, pack.benchmark_version,
    )
    logging.info(f"Quality log → {log_path}")
    logging.info("=" * 60)

    # Pipeline execution
    valid_df, error_df = process_folder(input_dir)
    meta = pack.metadata()
    if not valid_df.empty:
        attach_benchmark_columns(valid_df, meta)
    if not error_df.empty:
        attach_benchmark_columns(error_df, meta)

    # Enforce frozen schema before any data reaches disk
    if not valid_df.empty:
        validate_output_schema(valid_df, TASKS_PARQUET_SCHEMA)

    # TECHNICAL DECISION — Partition by split then task_id:
    #   Queries that filter by split (e.g. "give me all train grids") skip the
    #   task_id directories entirely.  Adding task_id as a second level lets
    #   downstream code load a single task cheaply.  With ~400 tasks the number
    #   of leaf directories stays manageable.
    save_partitioned_parquet(
        valid_df,
        output_dir,
        partition_cols=["split", "task_id"],
        label="analytical base",
    )
    save_partitioned_parquet(
        error_df,
        error_dir,
        partition_cols=["split", "task_id"],
        label="errors",
    )

    n_tasks = (
        int(valid_df["task_id"].nunique()) if not valid_df.empty
        else count_task_files(input_dir)
    )
    sidecar = write_pack_sidecar(output_dir, pack, n_tasks=n_tasks)
    logging.info("Benchmark pack sidecar → %s", sidecar)
    _warn_if_corpus_mixes_packs(output_dir, pack.pack_id)

    logging.info("=" * 60)
    logging.info("ETL FINISHED")
    logging.info("=" * 60)


if __name__ == "__main__":
    main()

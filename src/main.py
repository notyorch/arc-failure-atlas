import json
import hashlib
import logging
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter

# LOGGING CONFIGURATION
# Extended format with function name for better traceability
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s'
)

# PIPELINE CONSTANTS
# Centralizing these values avoids "magic strings" scattered in the code
PIPELINE_VERSION = "1.1.0"
VALID_SPLITS     = ["train", "test"]
VALID_ROLES      = ["input", "output"]
ARC_COLOR_MIN    = 0
ARC_COLOR_MAX    = 9

# ARCHITECTURE NOTE (deferred fields for inference sprint)
# The following fields will be added when the pipeline ingests
# responses from AI models (Nvidia, OpenAI, Ollama):
#   prompt_version, latency_ms, cost, correct, attempt,
#   inference_timestamp, task_version, model_id

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

def transform_task_to_rows(task_json: dict, task_id: str) -> tuple:
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
        pipeline_version, ingested_at

    Returns: (valid_df, error_df)
        - valid_df: clean rows ready for analysis
        - error_df: record of rejected grids for auditing
    """
    logging.info(f"[{task_id}] Starting transformation...")
    valid_rows = []
    error_rows = []
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
                    logging.warning(
                        f"[{task_id}] Grid rejected → "
                        f"split={split}, example={example_id}, role={role}: {error_message}"
                    )
                    error_rows.append({
                        "task_id":    task_id,
                        "split":      split,
                        "example_id": example_id,
                        "grid_role":  role,
                        "error":      error_message,
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


# ENTRY POINT

if __name__ == "__main__":
    logging.info("=" * 60)
    logging.info(f"STARTING ARC-AGI ETL  |  pipeline_version={PIPELINE_VERSION}")
    logging.info("=" * 60)

    # Paths
    # TECHNICAL DECISION: Naming convention for Parquet:
    #   {task_id}_data.parquet for valid rows ready for analysis
    #   {task_id}_errors.parquet for rejected grids for auditing
    # The task_id prefix facilitates partitioning when processing
    # the 400 real files (the outer loop only changes this path).
    input_file    = Path('data/raw/dummy_task.json')
    output_dir    = Path('data/parquet')
    task_id       = input_file.stem  # "dummy_task"

    data_path   = output_dir / f"{task_id}_data.parquet"
    error_path  = output_dir / f"{task_id}_errors.parquet"

    # Pipeline execution
    raw_data              = extract_json_data(input_file)
    valid_df, error_df    = transform_task_to_rows(raw_data, task_id=task_id)

    save_as_parquet(valid_df,   data_path,   label="analytical base")
    save_as_parquet(error_df,  error_path, label="errors")

    logging.info("=" * 60)
    logging.info("ETL FINISHED")
    logging.info("=" * 60)

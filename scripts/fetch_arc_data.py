"""
Populate data/raw/evaluation/ with ARC-AGI task JSON files.

Two modes:

1. Download the public ARC-AGI-1 dataset (fchollet/ARC-AGI) — needs network:
       python scripts/fetch_arc_data.py --limit 20
       python scripts/fetch_arc_data.py --dataset training --limit 50

2. Offline sample mode — copies the bundled fixtures from
   tests/fixtures/sample_tasks/ so the full pipeline runs with no network:
       python scripts/fetch_arc_data.py --sample

The ETL (src/main.py) then reads every *.json in data/raw/evaluation/.
Files are only written, never deleted; re-running overwrites same-named files.
"""

import argparse
import io
import shutil
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DEST = REPO_ROOT / "data" / "raw" / "evaluation"
SAMPLE_DIR = REPO_ROOT / "tests" / "fixtures" / "sample_tasks"

# Single-request download: the repo zip archive (~1 MB) instead of ~400
# individual raw.githubusercontent requests.
ARC_ZIP_URL = "https://github.com/fchollet/ARC-AGI/archive/refs/heads/master.zip"


def copy_samples(dest: Path) -> int:
    """Copy bundled sample tasks into dest. Returns number of files copied."""
    files = sorted(SAMPLE_DIR.glob("*.json"))
    if not files:
        sys.exit(f"ERROR: no sample fixtures found in {SAMPLE_DIR}")
    dest.mkdir(parents=True, exist_ok=True)
    for f in files:
        shutil.copy2(f, dest / f.name)
    return len(files)


def download_dataset(dest: Path, dataset: str, limit: int | None) -> int:
    """Download ARC-AGI-1 <dataset> tasks from GitHub. Returns files written."""
    print(f"Downloading {ARC_ZIP_URL} ...")
    try:
        with urllib.request.urlopen(ARC_ZIP_URL, timeout=120) as resp:
            payload = resp.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        sys.exit(
            f"ERROR: could not download ARC-AGI dataset ({exc}).\n"
            "No network? Run the offline mode instead:\n"
            "    python scripts/fetch_arc_data.py --sample"
        )

    prefix = f"ARC-AGI-master/data/{dataset}/"
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        names = sorted(
            n for n in zf.namelist()
            if n.startswith(prefix) and n.endswith(".json")
        )
        if not names:
            sys.exit(f"ERROR: no tasks found under '{prefix}' in the archive.")
        if limit is not None:
            names = names[:limit]

        dest.mkdir(parents=True, exist_ok=True)
        for name in names:
            target = dest / Path(name).name
            target.write_bytes(zf.read(name))
    return len(names)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument(
        "--dataset", choices=["evaluation", "training"], default="evaluation",
        help="which ARC-AGI-1 dataset to download (default: evaluation)",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="download only the first N tasks (alphabetical); default: all",
    )
    parser.add_argument(
        "--sample", action="store_true",
        help="offline mode: copy bundled sample tasks instead of downloading",
    )
    parser.add_argument(
        "--dest", type=Path, default=DEFAULT_DEST,
        help=f"destination directory (default: {DEFAULT_DEST})",
    )
    args = parser.parse_args()

    if args.sample:
        n = copy_samples(args.dest)
        print(f"Copied {n} sample task(s) → {args.dest}")
    else:
        n = download_dataset(args.dest, args.dataset, args.limit)
        print(f"Downloaded {n} task(s) from ARC-AGI-1 {args.dataset} → {args.dest}")

    print("Next step:  python src/main.py")


if __name__ == "__main__":
    main()

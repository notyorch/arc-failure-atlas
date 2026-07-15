"""
Run/build manifest files for experiment traceability.

Every inference run directory and every analytics build gets a
`_manifest.json` describing exactly what produced it: git commit,
timestamps, provider/model/prompt version, schema versions, and
input/output paths.

The filename starts with an underscore on purpose: pyarrow dataset
discovery ignores files with '.'/'_' prefixes, so manifests can live inside
Parquet directory trees without breaking `pd.read_parquet(<dir>)`.
"""

import json
import subprocess
from pathlib import Path

MANIFEST_FILENAME = "_manifest.json"

REPO_ROOT = Path(__file__).resolve().parent.parent


def git_commit_sha() -> str:
    """Current commit SHA, or 'unknown' outside git / without the git binary."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"


def portable_path(path: Path) -> str:
    """Repo-relative POSIX path when possible (portable), else absolute."""
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def write_manifest(directory: Path, payload: dict) -> Path:
    """Writes/overwrites the manifest in `directory`. Returns its path."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / MANIFEST_FILENAME
    manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest_path

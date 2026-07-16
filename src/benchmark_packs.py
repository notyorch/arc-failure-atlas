"""
First-class benchmark packs — versioned task corpora for the evaluator.

A pack is a directory under ``benchmark_packs/<pack_id>/`` (or any local path)
containing:

    manifest.json   — identity + provenance (required)
    <tasks_dir>/    — flat ``*.json`` ARC task files (default: ``tasks/``)

Manifest fields (see ``benchmark_packs/*/manifest.json``):

    pack_id, benchmark_family, benchmark_name, benchmark_version,
    task_source, split_name, tasks_dir, task_format, …

Selection (CLI / env):

    --benchmark-pack arc_agi_2          resolve under benchmark_packs/
    --benchmark-pack-path /abs/or/rel   path to pack root (has manifest.json)
    ATLAS_BENCHMARK_PACK               same as --benchmark-pack

Legacy ETL without a pack flag still works: tasks come from
``data/raw/evaluation/`` and rows are stamped with
``LEGACY_RAW_DIR_META`` so new columns stay populated.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PACKS_ROOT = REPO_ROOT / "benchmark_packs"
MANIFEST_NAME = "manifest.json"
SIDECAR_NAME = "_benchmark_pack.json"
DEFAULT_TASKS_DIR = "tasks"

# Columns stamped onto tasks Parquet + evaluation result rows.
BENCHMARK_METADATA_FIELDS = (
    "pack_id",
    "benchmark_family",
    "benchmark_name",
    "benchmark_version",
    "split_name",
    "task_source",
)

# Used when ETL runs with --input-dir only (pre-pack workflow).
LEGACY_RAW_DIR_META = {
    "pack_id": "legacy_raw_dir",
    "benchmark_family": "arc_agi",
    "benchmark_name": "ARC-AGI-1",
    "benchmark_version": "legacy-unpinned",
    "split_name": "evaluation",
    "task_source": "legacy_raw_dir",
}

UNKNOWN_META = {
    "pack_id": "unknown",
    "benchmark_family": "unknown",
    "benchmark_name": "unknown",
    "benchmark_version": "unknown",
    "split_name": "unknown",
    "task_source": "unknown",
}


class BenchmarkPackError(ValueError):
    """Invalid pack path, missing manifest, or empty tasks directory."""


@dataclass(frozen=True)
class BenchmarkPack:
    """Resolved pack identity + filesystem locations."""

    pack_id: str
    pack_root: Path
    tasks_dir: Path
    benchmark_family: str
    benchmark_name: str
    benchmark_version: str
    task_source: str
    split_name: str
    task_format: str = "arc_json"
    task_count: int = 0
    notes: str = ""
    license_or_usage_notes: str = ""
    manifest_path: Optional[Path] = None
    extra: Optional[dict] = None

    def metadata(self) -> dict[str, str]:
        """Flat stamp for Parquet / evaluation rows."""
        return {
            "pack_id": self.pack_id,
            "benchmark_family": self.benchmark_family,
            "benchmark_name": self.benchmark_name,
            "benchmark_version": self.benchmark_version,
            "split_name": self.split_name,
            "task_source": self.task_source,
        }

    def to_sidecar(self, n_tasks: Optional[int] = None) -> dict[str, Any]:
        payload = {
            "manifest_kind": "benchmark_pack",
            **self.metadata(),
            "task_format": self.task_format,
            "pack_root": _portable(self.pack_root),
            "tasks_dir": _portable(self.tasks_dir),
            "manifest_path": (
                _portable(self.manifest_path) if self.manifest_path else None
            ),
            "task_count": n_tasks if n_tasks is not None else self.task_count,
            "notes": self.notes,
            "license_or_usage_notes": self.license_or_usage_notes,
        }
        if self.extra:
            payload["extra"] = self.extra
        return payload


def _portable(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _require_str(raw: dict, key: str, label: str) -> str:
    if key not in raw or raw[key] is None or str(raw[key]).strip() == "":
        raise BenchmarkPackError(f"{label}: missing required field {key!r}")
    return str(raw[key]).strip()


def load_manifest(manifest_path: Path) -> dict[str, Any]:
    path = Path(manifest_path)
    if not path.is_file():
        raise BenchmarkPackError(f"manifest not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BenchmarkPackError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise BenchmarkPackError(f"{path}: manifest root must be an object")
    return data


def pack_from_manifest(pack_root: Path, raw: Optional[dict] = None) -> BenchmarkPack:
    """Build a BenchmarkPack from ``pack_root/manifest.json`` (or given dict)."""
    root = Path(pack_root).resolve()
    manifest_path = root / MANIFEST_NAME
    data = raw if raw is not None else load_manifest(manifest_path)

    pack_id = str(data.get("pack_id") or root.name).strip()
    tasks_rel = str(data.get("tasks_dir") or DEFAULT_TASKS_DIR).strip()
    tasks_dir = Path(tasks_rel)
    if not tasks_dir.is_absolute():
        tasks_dir = (root / tasks_dir).resolve()
    else:
        tasks_dir = tasks_dir.resolve()

    known = {
        "pack_id", "benchmark_family", "benchmark_name", "benchmark_version",
        "task_source", "split_name", "tasks_dir", "task_format", "task_count",
        "notes", "license_or_usage_notes", "task_id_pattern",
    }
    extra = {k: v for k, v in data.items() if k not in known}

    return BenchmarkPack(
        pack_id=pack_id,
        pack_root=root,
        tasks_dir=tasks_dir,
        benchmark_family=_require_str(data, "benchmark_family", pack_id),
        benchmark_name=_require_str(data, "benchmark_name", pack_id),
        benchmark_version=_require_str(data, "benchmark_version", pack_id),
        task_source=_require_str(data, "task_source", pack_id),
        split_name=_require_str(data, "split_name", pack_id),
        task_format=str(data.get("task_format") or "arc_json"),
        task_count=int(data.get("task_count") or 0),
        notes=str(data.get("notes") or ""),
        license_or_usage_notes=str(data.get("license_or_usage_notes") or ""),
        manifest_path=manifest_path if manifest_path.is_file() else None,
        extra=extra or None,
    )


def list_registered_packs(packs_root: Path = DEFAULT_PACKS_ROOT) -> list[BenchmarkPack]:
    """Discover ``benchmark_packs/*/manifest.json`` (sorted by pack_id)."""
    root = Path(packs_root)
    if not root.is_dir():
        return []
    packs = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / MANIFEST_NAME).is_file():
            packs.append(pack_from_manifest(child))
    return packs


def format_pack_list(packs_root: Path = DEFAULT_PACKS_ROOT) -> str:
    packs = list_registered_packs(packs_root)
    if not packs:
        return f"(no packs found under {packs_root})"
    lines = ["Registered benchmark packs:", ""]
    for pack in packs:
        n_files = count_task_files(pack.tasks_dir)
        status = f"{n_files} task file(s)" if n_files else "tasks dir empty / missing"
        lines.append(
            f"  {pack.pack_id:24s}  {pack.benchmark_name}  "
            f"({pack.benchmark_version})  [{status}]"
        )
        lines.append(f"    tasks_dir: {_portable(pack.tasks_dir)}")
    return "\n".join(lines)


def resolve_pack(
    pack_id: Optional[str] = None,
    pack_path: Optional[Path] = None,
    packs_root: Path = DEFAULT_PACKS_ROOT,
) -> BenchmarkPack:
    """
    Resolve a pack by id (under packs_root) or by explicit path.

    ``pack_path`` may be the pack root (directory with manifest.json) or the
    manifest file itself. ``pack_id`` and ``pack_path`` are mutually exclusive
    in the CLIs; if both are passed here, ``pack_path`` wins.
    """
    if pack_path is not None:
        path = Path(pack_path)
        if path.is_file() and path.name == MANIFEST_NAME:
            return pack_from_manifest(path.parent)
        if path.is_dir():
            if (path / MANIFEST_NAME).is_file():
                return pack_from_manifest(path)
            raise BenchmarkPackError(
                f"no {MANIFEST_NAME} under {path}. "
                "Pass a pack root or a registered --benchmark-pack id."
            )
        raise BenchmarkPackError(f"benchmark pack path not found: {path}")

    if pack_id:
        name = pack_id.strip()
        candidate = Path(packs_root) / name
        if (candidate / MANIFEST_NAME).is_file():
            return pack_from_manifest(candidate)
        available = [p.pack_id for p in list_registered_packs(packs_root)]
        raise BenchmarkPackError(
            f"unknown benchmark pack {name!r}. "
            f"Available: {available or '(none)'}. "
            f"Or pass --benchmark-pack-path to a local pack directory."
        )

    raise BenchmarkPackError(
        "select a pack with --benchmark-pack <id> or --benchmark-pack-path <dir>"
    )


def count_task_files(tasks_dir: Path) -> int:
    if not Path(tasks_dir).is_dir():
        return 0
    return len(list(Path(tasks_dir).glob("*.json")))


def require_tasks_dir(pack: BenchmarkPack) -> Path:
    """Fail fast if the pack has no task JSON files to ingest."""
    tasks_dir = pack.tasks_dir
    if not tasks_dir.is_dir():
        raise BenchmarkPackError(
            f"pack {pack.pack_id!r}: tasks directory missing: {tasks_dir}\n"
            f"Create it or set \"tasks_dir\" in {pack.pack_root / MANIFEST_NAME}.\n"
            "For ARC-AGI-2, place/symlink public evaluation JSON files there "
            "(see docs/BENCHMARK_PACKS.md)."
        )
    n = count_task_files(tasks_dir)
    if n == 0:
        raise BenchmarkPackError(
            f"pack {pack.pack_id!r}: no *.json tasks in {tasks_dir}\n"
            "Populate the directory before running ETL."
        )
    return tasks_dir


def legacy_pack(tasks_dir: Path) -> BenchmarkPack:
    """Synthetic pack for the historic ``data/raw/evaluation`` workflow."""
    return BenchmarkPack(
        pack_id=LEGACY_RAW_DIR_META["pack_id"],
        pack_root=Path(tasks_dir).resolve().parent,
        tasks_dir=Path(tasks_dir).resolve(),
        benchmark_family=LEGACY_RAW_DIR_META["benchmark_family"],
        benchmark_name=LEGACY_RAW_DIR_META["benchmark_name"],
        benchmark_version=LEGACY_RAW_DIR_META["benchmark_version"],
        task_source=LEGACY_RAW_DIR_META["task_source"],
        split_name=LEGACY_RAW_DIR_META["split_name"],
        notes="Default stamp when ETL runs without --benchmark-pack",
    )


def attach_benchmark_columns(dataframe, meta: dict[str, str]):
    """Stamp BENCHMARK_METADATA_FIELDS onto a DataFrame (in place + return)."""
    import pandas as pd  # local: keep module import-light for --help paths

    if dataframe is None or (isinstance(dataframe, pd.DataFrame) and dataframe.empty):
        return dataframe
    for key in BENCHMARK_METADATA_FIELDS:
        dataframe[key] = meta.get(key, UNKNOWN_META[key])
    return dataframe


def write_pack_sidecar(output_dir: Path, pack: BenchmarkPack,
                       n_tasks: Optional[int] = None) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / SIDECAR_NAME
    path.write_text(
        json.dumps(pack.to_sidecar(n_tasks=n_tasks), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def load_pack_sidecar(parquet_dir: Path) -> Optional[dict[str, Any]]:
    path = Path(parquet_dir) / SIDECAR_NAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def metadata_from_tasks_frame(df) -> dict[str, str]:
    """
    Prefer columns already on the tasks Parquet; else sidecar; else unknown.
    Assumes a single pack per tasks directory (platform convention).
    """
    for key in BENCHMARK_METADATA_FIELDS:
        if key not in df.columns:
            break
    else:
        # All present — take the first row (homogeneous by construction).
        row = df.iloc[0]
        return {k: str(row[k]) for k in BENCHMARK_METADATA_FIELDS}

    return dict(UNKNOWN_META)


def metadata_for_evaluation_items(
    tasks_df,
    parquet_dir: Path,
    pack_override: Optional[BenchmarkPack] = None,
) -> dict[str, str]:
    """Resolve pack metadata for stamping evaluation items/rows."""
    if pack_override is not None:
        return pack_override.metadata()
    meta = metadata_from_tasks_frame(tasks_df)
    if meta["pack_id"] != "unknown":
        return meta
    sidecar = load_pack_sidecar(parquet_dir)
    if sidecar:
        return {k: str(sidecar.get(k, UNKNOWN_META[k])) for k in BENCHMARK_METADATA_FIELDS}
    return dict(UNKNOWN_META)

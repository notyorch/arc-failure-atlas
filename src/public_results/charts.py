"""Charts for public-results vs local pilot context."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
BASELINE = "#c3c2b7"
SERIES_PUBLIC = "#2a78d6"
SERIES_LOCAL = "#c2410c"
SERIES_SELF = "#898781"


def write_score_context_chart(
    df: pd.DataFrame,
    out_path: Path,
    *,
    local_run_id: Optional[str] = None,
    title: str = "Public leaderboard context vs local pilot",
) -> Path:
    """
    Horizontal bar chart of score_percent for a readable subset of rows.
    Local pilot bars use a distinct color.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError(
            "matplotlib is required for public-results charts "
            "(pip install -r requirements.txt)"
        ) from exc

    work = df.copy()
    # Drop sentinel preview zeros
    work = work[~((work["score"] == 0) & (work["trust_tier"] == "preview"))]
    if local_run_id:
        # Keep all local matching + top public by score within each benchmark
        local_mask = work["local_run_id"].astype(str) == str(local_run_id)
        public = work[~local_mask].sort_values("score", ascending=False)
        # Cap public bars for readability
        public = public.head(12)
        work = pd.concat([work[local_mask], public], ignore_index=True)
    else:
        work = work.sort_values("score", ascending=False).head(14)

    work = work.sort_values("score", ascending=True)
    labels = [
        f"{r.submission_name[:42]} [{r.benchmark_name}]"
        for r in work.itertuples(index=False)
    ]
    colors = []
    for r in work.itertuples(index=False):
        if r.trust_tier == "local_pilot":
            colors.append(SERIES_LOCAL)
        elif r.trust_tier == "self_reported":
            colors.append(SERIES_SELF)
        else:
            colors.append(SERIES_PUBLIC)

    fig, ax = plt.subplots(figsize=(10, max(4.5, 0.38 * len(work) + 1.5)), dpi=144)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color(BASELINE)
    ax.grid(axis="x", color=GRIDLINE, linewidth=0.8)
    ax.set_axisbelow(True)

    y = range(len(work))
    ax.barh(list(y), work["score_percent"].astype(float), color=colors, height=0.65)
    ax.set_yticks(list(y), labels, fontsize=8, color=INK_SECONDARY)
    ax.set_xlabel("score %", fontsize=9, color=INK_MUTED)
    ax.set_xlim(0, max(100.0, float(work["score_percent"].max()) * 1.05))
    ax.tick_params(colors=INK_MUTED, length=0)
    fig.text(0.02, 0.98, title, ha="left", va="top", fontsize=12,
             fontweight="semibold", color=INK)
    fig.text(
        0.02, 0.935,
        "Orange = local pilot (partial). Blue = public verified/competition. "
        "Grey = self-reported. Not a controlled bake-off.",
        ha="left", va="top", fontsize=8, color=INK_SECONDARY,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.90))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)
    return out_path

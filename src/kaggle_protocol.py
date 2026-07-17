"""
Kaggle / ARC Prize protocol parity — strict submission checks and the
official leaderboard metric.

The generic validators in submission_io accept many artifact shapes and only
check task-level coverage. Kaggle is stricter: the grader expects EVERY task
of the evaluation set, EVERY test example of every task, and BOTH attempt
keys (`attempt_1`, `attempt_2`) per test output. A file that scores fine
here but violates any of that fails (or silently underscores) on the real
leaderboard. This module encodes those rules so a pre-submit check can say
"Kaggle will accept and fully score this file" — or exactly why not.

Official metric (`kaggle_score`, ARC Prize leaderboard semantics):
    per test output : 1 if ANY of the first 2 attempts is an exact match
    per task        : mean over its test outputs
    leaderboard     : mean over tasks

This sits between the platform's `solved_rate` (item-level) and
`task_solved_rate` (all-or-nothing per task): a task with 1 of 2 test
outputs correct contributes 0.5 here, 0 to task_solved_rate.

Nothing in this module runs solvers or reads ground truth grids directly —
strict validation needs only the *shape* of the evaluation set (how many
test examples each task has), and scoring consumes already-scored rows.
"""

from __future__ import annotations

from typing import Optional

from submission_io import CanonicalSubmission, ValidationIssue

KAGGLE_REQUIRED_ATTEMPTS = (1, 2)


def test_counts_from_tasks_df(tasks_df) -> dict:
    """
    task_id → number of test examples, from the long-format tasks Parquet
    (one row per grid; test inputs identify the gradable outputs).
    """
    mask = (tasks_df["split"] == "test") & (tasks_df["grid_role"] == "input")
    counts = (
        tasks_df.loc[mask]
        .groupby("task_id", observed=True)["example_id"]
        .nunique()
    )
    return {str(task_id): int(n) for task_id, n in counts.items()}


def test_counts_from_items(items: list) -> dict:
    """task_id → number of test examples, from evaluation items."""
    counts: dict = {}
    for item in items:
        counts[item["task_id"]] = counts.get(item["task_id"], 0) + 1
    return counts


def _issue(severity: str, code: str, message: str,
           task_id: Optional[str] = None,
           test_index: Optional[int] = None) -> ValidationIssue:
    return ValidationIssue(severity, code, message, task_id, test_index)


def kaggle_strict_issues(submission: CanonicalSubmission,
                         expected_counts: dict) -> list:
    """
    Issues a Kaggle grader would raise on this artifact, given the expected
    evaluation-set shape (task_id → n test examples).

    errors  : missing_task, missing_test_output, missing_attempt
    warnings: extra_task, extra_test_output, extra_attempt
    """
    issues: list = []
    covered: dict = {}
    for pred in submission.predictions:
        covered.setdefault(pred.task_id, {}).setdefault(
            pred.test_index, set()
        ).add(pred.candidate_rank)

    missing_tasks = sorted(set(expected_counts) - set(covered))
    if len(missing_tasks) > 10:
        # One aggregated error beats hundreds of identical lines; the
        # coverage report lists the ids.
        issues.append(_issue(
            "error", "missing_task",
            f"{len(missing_tasks)} of {len(expected_counts)} evaluation "
            "tasks are absent — Kaggle requires every task (see the "
            "coverage report for ids)",
        ))
    else:
        for task_id in missing_tasks:
            issues.append(_issue(
                "error", "missing_task",
                f"task '{task_id}' is absent — Kaggle requires every task "
                "of the evaluation set",
                task_id,
            ))

    for task_id in sorted(expected_counts):
        n_tests = expected_counts[task_id]
        task_cov = covered.get(task_id)
        if not task_cov:
            continue
        for test_index in range(1, n_tests + 1):
            ranks = task_cov.get(test_index)
            if not ranks:
                issues.append(_issue(
                    "error", "missing_test_output",
                    f"task '{task_id}' test {test_index}: no prediction "
                    f"(task has {n_tests} test example(s))",
                    task_id, test_index,
                ))
                continue
            for rank in KAGGLE_REQUIRED_ATTEMPTS:
                if rank not in ranks:
                    issues.append(_issue(
                        "error", "missing_attempt",
                        f"task '{task_id}' test {test_index}: attempt_{rank} "
                        "missing — Kaggle requires both attempt_1 and "
                        "attempt_2 (duplicate your best guess if you only "
                        "have one)",
                        task_id, test_index,
                    ))
            extra_ranks = sorted(r for r in ranks
                                 if r not in KAGGLE_REQUIRED_ATTEMPTS)
            if extra_ranks:
                issues.append(_issue(
                    "warning", "extra_attempt",
                    f"task '{task_id}' test {test_index}: attempts "
                    f"{extra_ranks} beyond attempt_2 are ignored by Kaggle",
                    task_id, test_index,
                ))
        extra_tests = sorted(t for t in task_cov if t > n_tests or t < 1)
        for test_index in extra_tests:
            issues.append(_issue(
                "warning", "extra_test_output",
                f"task '{task_id}' test {test_index}: task only has "
                f"{n_tests} test example(s)",
                task_id, test_index,
            ))

    for task_id in sorted(set(covered) - set(expected_counts)):
        issues.append(_issue(
            "warning", "extra_task",
            f"task '{task_id}' is not in the evaluation set (ignored by "
            "the grader)",
            task_id,
        ))
    return issues


def coverage_summary(submission: CanonicalSubmission,
                     expected_counts: dict) -> dict:
    """Coverage numbers a tester reads before anything else."""
    covered_items: set = set()
    for pred in submission.predictions:
        covered_items.add((pred.task_id, pred.test_index))
    expected_items = {
        (task_id, test_index)
        for task_id, n in expected_counts.items()
        for test_index in range(1, n + 1)
    }
    covered_tasks = {t for t, _ in covered_items}
    missing_tasks = sorted(set(expected_counts) - covered_tasks)
    return {
        "n_expected_tasks": len(expected_counts),
        "n_covered_tasks": len(set(expected_counts) & covered_tasks),
        "missing_task_ids": missing_tasks,
        "n_expected_items": len(expected_items),
        "n_covered_items": len(expected_items & covered_items),
    }


def format_coverage_report(cov: dict) -> str:
    lines = [
        f"coverage      : {cov['n_covered_tasks']} / "
        f"{cov['n_expected_tasks']} task(s), "
        f"{cov['n_covered_items']} / {cov['n_expected_items']} "
        "test output(s)",
    ]
    missing = cov["missing_task_ids"]
    if missing:
        shown = ", ".join(missing[:10])
        suffix = f" … (+{len(missing) - 10} more)" if len(missing) > 10 else ""
        lines.append(f"missing tasks : {shown}{suffix}")
    return "\n".join(lines)


def kaggle_score_from_rows(rows_df) -> dict:
    """
    Official leaderboard metric over scored attempt rows (the evaluation
    Parquet schema: task_id, test_example_id, attempt, is_exact_match).

    Only attempts 1–2 count. Items whose truth was unavailable
    (is_exact_match all-NULL with no attempt data) still count as unsolved —
    on Kaggle the grader always has the truth.
    """
    import pandas as pd  # scoring callers already depend on pandas

    if rows_df is None or len(rows_df) == 0:
        return {"kaggle_score": None, "n_tasks": 0, "n_items": 0}

    df = rows_df.loc[rows_df["attempt"].isin(KAGGLE_REQUIRED_ATTEMPTS),
                     ["task_id", "test_example_id", "is_exact_match"]].copy()
    if df.empty:
        return {"kaggle_score": None, "n_tasks": 0, "n_items": 0}
    df["_solved"] = df["is_exact_match"].eq(True).fillna(False)
    per_item = (
        df.groupby(["task_id", "test_example_id"], sort=False)["_solved"]
        .any()
    )
    per_task = per_item.groupby("task_id").mean()
    return {
        "kaggle_score": float(per_task.mean()),
        "n_tasks": int(per_task.size),
        "n_items": int(per_item.size),
    }

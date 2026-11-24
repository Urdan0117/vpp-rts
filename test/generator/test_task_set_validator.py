"""Tests for TaskSetValidator tail-fit and job-count rules."""

from src.generator.task_set_generator import TaskSetGenerator
from src.generator.task_set_validator import TaskSetValidator

H = 72


def _task(r: int, p: int, e: int, d: int, w: int = 10) -> dict:
    return {"r": r, "p": p, "e": e, "d": d, "w": w, "preempt": 1}


def test_tail_job_that_cannot_fit_is_rejected() -> None:
    # releases 7, 15, ..., 71; the t=71 instance only has ticks 71-72 (< e=4)
    v = TaskSetValidator(H)
    assert not v._validate_tail_jobs_fit({"p1": _task(r=7, p=8, e=4, d=4)})


def test_tail_job_truncated_but_fitting_is_accepted() -> None:
    # releases 1, 9, ..., 65; last window 65-68 fits e=4
    v = TaskSetValidator(H)
    assert v._validate_tail_jobs_fit({"p1": _task(r=1, p=8, e=4, d=4)})
    # release 70, deadline 79 > H, but ticks 70-72 still fit e=3
    assert v._validate_tail_jobs_fit({"p1": _task(r=10, p=12, e=3, d=10)})


def test_job_count_includes_every_release_within_horizon() -> None:
    # r=1, p=8 -> releases 1..65 = 9 instances; r=7, p=8 -> 7..71 = 9 instances
    v = TaskSetValidator(H)
    assert len(v._job_releases(_task(r=1, p=8, e=1, d=1))) == 9
    assert len(v._job_releases(_task(r=7, p=8, e=1, d=1))) == 9


def test_generated_sets_never_contain_unfittable_tail_jobs() -> None:
    v = TaskSetValidator(H)
    for seed in range(30):
        tasks, _ = TaskSetGenerator(H, seed=seed).generate()
        assert v._validate_tail_jobs_fit(tasks), f"seed {seed}"

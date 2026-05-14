"""Prefect flow fixture — exercises @flow and @task decorators.

The discoverer should emit one DAG_TASK entry point per decorator.
We provide both a named flow (``@flow(name=...)``) and bare-decorator
tasks so the regex handling for both forms is covered.
"""

from __future__ import annotations

from prefect import flow, task


@task
def fetch_data() -> list[int]:
    """Pretend to fetch a payload — returns three integers."""
    return [1, 2, 3]


@task(name="aggregate-rows")
def aggregate(rows: list[int]) -> int:
    """Sum the incoming rows; the explicit name appears in Prefect UI."""
    return sum(rows)


@flow(name="hello-flow")
def hello_flow() -> int:
    """Top-level Prefect flow — fetches and aggregates."""
    rows = fetch_data()
    return aggregate(rows)


@flow
def secondary_flow() -> str:
    """A second flow with no explicit name kwarg."""
    return "done"

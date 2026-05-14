"""Dagster assets fixture — exercises @asset, @op, @graph, @job decorators.

Each decorator should produce ONE DAG_TASK entry point. The graph and
job combinations show how Dagster composes ops into reusable units.
"""

from __future__ import annotations

from dagster import asset, graph, job, op


@asset
def raw_orders() -> list[dict[str, int]]:
    """Pretend to load raw order rows from a source system."""
    return [{"id": 1, "total": 100}, {"id": 2, "total": 200}]


@asset(name="enriched_orders")
def _enriched(raw_orders: list[dict[str, int]]) -> list[dict[str, int]]:
    """Annotate each order with a derived field."""
    return [{**r, "tax": r["total"] // 10} for r in raw_orders]


@op
def fetch_op() -> int:
    """Imperative computation op — returns a single integer."""
    return 42


@op(name="multiply-op")
def multiply_op(x: int) -> int:
    """Multiply the upstream value by 3."""
    return x * 3


@graph
def fetch_and_multiply_graph() -> int:
    """Composite graph wiring fetch_op → multiply_op."""
    return multiply_op(fetch_op())


@job
def main_job() -> None:
    """Top-level Dagster job that executes the composite graph."""
    fetch_and_multiply_graph()

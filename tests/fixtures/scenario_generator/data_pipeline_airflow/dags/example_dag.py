"""Example Airflow DAG fixture — exercises both classic and TaskFlow APIs.

Two DAGs and three tasks. Enough surface for the discoverer to emit
multiple DAG_TASK entry points so the regression golden is non-trivial.
"""

from __future__ import annotations

from datetime import datetime

from airflow import DAG
from airflow.decorators import dag, task
from airflow.operators.python import PythonOperator


def _extract() -> dict[str, int]:
    """Pretend extraction step — return a tiny payload."""
    return {"rows": 3}


# Classic context-manager DAG with PythonOperator tasks.
with DAG(
    dag_id="etl_classic",
    start_date=datetime(2024, 1, 1),
    schedule=None,
    catchup=False,
) as etl_classic:
    extract = PythonOperator(
        task_id="extract",
        python_callable=_extract,
    )
    load = PythonOperator(
        task_id="load",
        python_callable=lambda: None,
    )
    extract >> load


# TaskFlow-API DAG: @dag + @task decorators.
@dag(
    dag_id="etl_taskflow",
    start_date=datetime(2024, 1, 1),
    schedule=None,
    catchup=False,
)
def etl_taskflow() -> None:
    """ETL pipeline built with the TaskFlow API."""

    @task
    def transform(payload: dict[str, int]) -> int:
        """Multiply the rows count by 2 as a stand-in transform."""
        return payload["rows"] * 2

    transform({"rows": 10})


etl_taskflow_dag = etl_taskflow()

"""Per-type discoverers.

Each module in this package exposes:
    def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]

The module filename equals the software-type name (e.g. web_python_fastapi.py
discovers entry points when web_service_python is detected; the dispatch
table is in emit_scenarios_json._load_discoverer which falls back to
unknown_software.py when no specific discoverer exists for a type).
"""

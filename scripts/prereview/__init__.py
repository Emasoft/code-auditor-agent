"""CAA pre-review pipeline scripts (TRDD-7e364ace).

Deterministic, zero-LLM pre-flight detectors that emit structured JSON
the downstream Claude-model agents read instead of re-grepping. Each
module is a single-responsibility script invoked via:

    uv run --no-project python -m scripts.prereview.<module> <args>

Each script:
- Is fully deterministic (two runs on the same repo → byte-identical JSON).
- Reads files from disk; never holds the whole repo in memory.
- Emits its findings to <main-repo>/reports/caa-prereview/<ts>-<name>.json.
- Returns a non-zero exit code only on infrastructure failure (bad CLI args,
  unreadable repo root). Detection findings themselves are always reported
  via the JSON file, never via exit code.
"""

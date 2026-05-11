#!/usr/bin/env python3
"""scenarios.md emitter — human-readable companion to scenarios.json.

Reads a scenarios.json on stdin or from a file and prints a markdown
index grouped by type_origin, then by family, with one line per scenario.

Usage:
    uv run python -m scripts.scenario_generator.emit_scenarios_md <scenarios.json>

Deterministic — same input always produces same output.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path


def emit(scenarios_json: dict) -> str:
    """Render scenarios.json as a markdown table grouped by type+family."""
    lines: list[str] = []
    schema = scenarios_json.get("$schema", "scenarios.v?.json")
    ts = scenarios_json.get("generated_at", "unknown")
    cb = scenarios_json.get("codebase", {})
    types = cb.get("detected_types", [])
    langs = cb.get("detected_languages", [])
    scenarios = scenarios_json.get("scenarios", [])

    lines.append(f"# Scenarios — {ts}")
    lines.append("")
    lines.append(f"**Schema:** `{schema}`")
    lines.append(f"**Codebase root:** `{cb.get('root', '?')}`")
    lines.append(f"**Languages:** {', '.join(langs) if langs else '(none detected)'}")
    lines.append("")

    lines.append("## Detected software types")
    lines.append("")
    if types:
        lines.append("| Type | Confidence | Evidence (first match) |")
        lines.append("|---|---|---|")
        for t in types:
            first_ev = t.get("evidence", [""])[0] if t.get("evidence") else ""
            lines.append(f"| `{t['type']}` | {t['confidence']:.2f} | `{first_ev}` |")
    else:
        lines.append("(no types detected)")
    lines.append("")

    lines.append(f"## Scenarios ({len(scenarios)})")
    lines.append("")

    # Group by (type_origin, family) in sorted order.
    by_group: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for s in scenarios:
        by_group[(s["type_origin"], s["family"])].append(s)

    for type_origin, family in sorted(by_group):
        group = by_group[(type_origin, family)]
        lines.append(f"### `{type_origin}` × `{family}` ({len(group)})")
        lines.append("")
        lines.append("| id | entry | title |")
        lines.append("|---|---|---|")
        for s in group:
            ep = s["entry_point"]
            entry = f"{ep['file']}:{ep['line']} `{ep['symbol']}`"
            lines.append(f"| `{s['id']}` | {entry} | {s['title']} |")
        lines.append("")

    return "\n".join(lines) + "\n"


def main() -> int:
    if len(sys.argv) != 2:
        sys.stderr.write("Usage: emit_scenarios_md.py <scenarios.json>\n")
        return 2
    src = Path(sys.argv[1])
    if not src.exists():
        sys.stderr.write(f"Not found: {src}\n")
        return 1
    data = json.loads(src.read_text(encoding="utf-8"))
    sys.stdout.write(emit(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())

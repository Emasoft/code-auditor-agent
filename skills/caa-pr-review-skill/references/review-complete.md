# PR Review Complete — Presentation Format

## Table of Contents

- [Verdict Summary Template](#verdict-summary-template)
- [Field Descriptions](#field-descriptions)

## Verdict Summary Template

```
## PR Review Complete

**Verdict:** {REQUEST CHANGES / APPROVE WITH NITS / APPROVE}
**Dedup:** {raw_count} raw → {dedup_count} unique ({removed} duplicates removed)
**MUST-FIX:** {count} | **SHOULD-FIX:** {count} | **NIT:** {count}

### Must-Fix Issues:
1. [MF-001] {title} — {file:line} (Original: CC-P1-A0-001, SR-P1-002)
2. [MF-002] {title} — {file:line} (Original: CV-P1-003)

### Should-Fix:
1. [SF-001] {title} (Original: CC-P1-A1-005)

### Security Findings:
1. [SC-P1-001] {title} — {file:line} (Severity: {HIGH/MEDIUM/LOW})

### Full report: docs_dev/caa-pr-review-P1-{timestamp}.md
```

## Field Descriptions

- **Verdict**: REQUEST CHANGES if any MUST-FIX exists; APPROVE WITH NITS if only SHOULD-FIX/NIT; APPROVE if clean.
- **Dedup**: Shows how many raw findings were consolidated into unique findings.
- **Original**: Cross-references the finding IDs from the source agents (CC=correctness, CV=claims, SR=skeptical, SC=security).
- **Severity (Security)**: HIGH = exploitable, MEDIUM = potential risk, LOW = hardening suggestion.

# Model Selection Rules

## Table of Contents

- [Rules](#rules)

## Rules

- **Opus/Sonnet ONLY** for all code analysis, review, fix, reasoning, and audit tasks
- **Haiku PROHIBITED** for code analysis and code fixing -- it hallucinates on complex code and causes error loops
- Haiku is acceptable ONLY for: running shell commands, file moves, formatting, and simple maintenance
- When spawning subagents for code review or code fix: always specify `model: opus` or `model: sonnet`

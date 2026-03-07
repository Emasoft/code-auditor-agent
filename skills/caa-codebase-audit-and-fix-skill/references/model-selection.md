# Model Selection Rules

## Table of Contents
- [Model Requirements](#model-requirements)

## Model Requirements

- **Opus/Sonnet ONLY** for all code analysis, auditing, fixing, reasoning, and verification tasks
- **Haiku PROHIBITED** for code analysis and auditing — it hallucinates on complex code and causes error loops
- Haiku is acceptable ONLY for: running shell commands, file moves, formatting, and simple maintenance
- When spawning subagents for audit, fix, or verification phases: always specify `model: opus` or `model: sonnet`

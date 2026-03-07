# Model Selection Rules

## Table of Contents

- [Code Analysis Models](#code-analysis-models)
- [Haiku Usage](#haiku-usage)

## Code Analysis Models

- **Opus/Sonnet ONLY** for all code analysis, exploration, reasoning, and audit tasks
- **Haiku PROHIBITED** for code analysis — it hallucinates on complex code and causes error loops
- When spawning subagents for code review: always specify `model: opus` or `model: sonnet`

## Haiku Usage

Haiku is acceptable ONLY for:
- Running shell commands
- File moves
- Formatting
- Simple maintenance tasks

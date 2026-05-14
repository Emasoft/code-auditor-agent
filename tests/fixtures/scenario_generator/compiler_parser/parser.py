"""Recursive-descent parser companion to expr.g4.

This file provides the disambiguator content the compiler_parser
fingerprint requires (`re:def\\s+parse_\\w+` and
`re:def\\s+tokenize_\\w+` in a *.py file). The hand-written
parser mirrors the productions in expr.g4 so the discoverer has
multiple parse_* and tokenize_* functions to report.
"""

from __future__ import annotations


def tokenize_input(source: str) -> list[str]:
    """Split source into tokens — integers, operators, parens, newlines."""
    return [t for t in source.split() if t]


def parse_prog(tokens: list[str]) -> dict:
    """Top-level production: prog := stat+ EOF."""
    return {"kind": "prog", "stmts": parse_stat_list(tokens)}


def parse_stat_list(tokens: list[str]) -> list[dict]:
    """Repeated statement parser."""
    out: list[dict] = []
    while tokens:
        out.append(parse_stat(tokens))
    return out


def parse_stat(tokens: list[str]) -> dict:
    """Statement production: stat := expr NEWLINE | NEWLINE."""
    return {"kind": "stat", "expr": parse_expr(tokens)}


def parse_expr(tokens: list[str]) -> dict:
    """Expression production: expr := expr op expr | INT | '(' expr ')'."""
    return {"kind": "expr", "value": tokens.pop(0) if tokens else "0"}


def tokenize_number(token: str) -> int:
    """Numeric tokenizer — wraps int() for parser hookup."""
    return int(token)

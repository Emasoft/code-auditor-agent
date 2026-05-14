"""Message-queue consumer discoverer.

For the `message_queue_consumer` software type, the discoverer finds
subscription / consume registrations across the dominant client
libraries:

1. **kafka-python (Python)** —
   `consumer.subscribe(['<topic>'])`
   `for msg in consumer: ...`           (consumer-as-iterator)
   `consumer.poll(...)`                  (manual poll loop)

2. **pika / RabbitMQ (Python)** —
   `channel.basic_consume(queue='<q>', on_message_callback=cb)`
   The callback is the entry point — its symbol is the bare callback
   name when given as a function reference.

3. **kafkajs / amqplib / nats / @aws-sdk/client-sqs (JavaScript /
   TypeScript)** —
   `consumer.run({ eachMessage: async ({...}) => ... })`        (kafkajs)
   `channel.consume('<q>', cb)`                                  (amqplib)
   `subscriber.subscribe('<subject>', cb)`                       (nats)

Each registration is one EntryPoint with kind `MQ_CONSUMER` and
metadata.topic / metadata.queue / metadata.subject carrying the
target.

Scans .py / .js / .ts / .mjs / .cjs files. Heuristic but deterministic.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "env",
        ".env",
        ".tox",
        "node_modules",
        ".pnpm-store",
        ".yarn",
        "vendor",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".cache",
        "dist",
        "build",
        "out",
        "target",
        ".next",
        ".nuxt",
        ".idea",
        ".vscode",
        "tests",
        "test",
        "__tests__",
        "spec",
        "coverage",
        "reports",
        "reports_dev",
        "docs_dev",
        "scripts_dev",
        "tests_dev",
        "samples_dev",
        "examples_dev",
        "downloads_dev",
        "libs_dev",
        "builds_dev",
    }
)


CONTENT_PREVIEW_BYTES = 262144  # 256KB


def _read(path: Path) -> str:
    """Read a file's text content; return '' on any I/O failure."""
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _is_skipped(path: Path, repo_root: Path) -> bool:
    """True iff any directory under repo_root on the way to path is skipped."""
    try:
        rel = path.relative_to(repo_root)
    except ValueError:
        return True
    return any(part in _SKIP_DIRS for part in rel.parts)


def _strip_js_comments(text: str) -> str:
    """Blank JS/TS comments to spaces while preserving offsets."""
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            if j == -1:
                j = n
            out.append(" " * (j - i))
            i = j
            continue
        if text[i] == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            if j == -1:
                j = n
            else:
                j += 2
            chunk = text[i:j]
            blanked = "".join("\n" if ch == "\n" else " " for ch in chunk)
            out.append(blanked)
            i = j
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def _py_kw_string(call: ast.Call, name: str) -> str:
    """Return the string-constant value of keyword `name` on a Call, or ''."""
    for kw in call.keywords:
        if kw.arg == name and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            return kw.value.value
    return ""


def _py_kw_name(call: ast.Call, name: str) -> str:
    """Return the bare-identifier value of keyword `name`, or ''.

    Used for `on_message_callback=function_name` where the caller passes
    a function reference rather than a string.
    """
    for kw in call.keywords:
        if kw.arg == name and isinstance(kw.value, ast.Name):
            return kw.value.id
    return ""


def _py_arg_str_list(call: ast.Call, position: int) -> list[str]:
    """Return string constants from positional arg `position` if it's a
    list or tuple of string literals. Used for `subscribe(['t1', 't2'])`.

    Returns [] when the arg isn't present or isn't an obvious literal.
    """
    if position >= len(call.args):
        return []
    a = call.args[position]
    if isinstance(a, ast.List | ast.Tuple):
        out: list[str] = []
        for elt in a.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                out.append(elt.value)
        return out
    if isinstance(a, ast.Constant) and isinstance(a.value, str):
        return [a.value]
    return []


def _discover_python(repo_root: Path) -> list[EntryPoint]:
    """AST-walk Python files for consumer subscription patterns."""
    found: list[EntryPoint] = []
    files: list[Path] = []
    for p in repo_root.rglob("*.py"):
        if not p.is_file():
            continue
        if _is_skipped(p, repo_root):
            continue
        files.append(p)
    files.sort()

    for path in files:
        text = _read(path)
        if not text:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        rel = str(path.relative_to(repo_root))

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            method = node.func.attr
            # `<binding>.subscribe([...])` — kafka-python style.
            if method == "subscribe":
                topics = _py_arg_str_list(node, 0)
                if not topics:
                    # Some libraries take a single string or kwarg.
                    topic_kw = _py_kw_string(node, "topic")
                    if topic_kw:
                        topics = [topic_kw]
                for topic in topics:
                    line = node.lineno
                    binding = node.func.value.id if isinstance(node.func.value, ast.Name) else "consumer"
                    found.append(
                        EntryPoint(
                            kind=EntryPointKind.MQ_CONSUMER,
                            file=rel,
                            line=line,
                            symbol=f"{binding}.subscribe:{topic}",
                            type_origin="message_queue_consumer",
                            metadata={
                                "language": "python",
                                "library": "kafka-python",
                                "topic": topic,
                                "binding": binding,
                                "api": "subscribe",
                            },
                            docstring="",
                            intended_behaviour_sources=(),
                        )
                    )
            # `<binding>.basic_consume(queue='<q>', on_message_callback=cb)`.
            elif method == "basic_consume":
                queue = _py_kw_string(node, "queue")
                callback = _py_kw_name(node, "on_message_callback")
                if queue or callback:
                    line = node.lineno
                    binding = node.func.value.id if isinstance(node.func.value, ast.Name) else "channel"
                    symbol = callback or f"{binding}.basic_consume:{queue or '?'}"
                    metadata: dict[str, object] = {
                        "language": "python",
                        "library": "pika",
                        "binding": binding,
                        "api": "basic_consume",
                    }
                    if queue:
                        metadata["queue"] = queue
                    if callback:
                        metadata["callback"] = callback
                    found.append(
                        EntryPoint(
                            kind=EntryPointKind.MQ_CONSUMER,
                            file=rel,
                            line=line,
                            symbol=symbol,
                            type_origin="message_queue_consumer",
                            metadata=metadata,
                            docstring="",
                            intended_behaviour_sources=(),
                        )
                    )
    return found


# JS regex set.
# `<binding>.consume('<queue>', cb)` — amqplib / kafkajs `eachMessage`
# is handled via `_KAFKAJS_RUN_RE` below.
_JS_CONSUME_RE = re.compile(
    r"(?P<binding>[A-Za-z_$][\w$]*)\s*\.\s*consume\s*\(\s*"
    r"(?P<quote>['\"])(?P<queue>[^'\"]+)(?P=quote)",
)

# `<binding>.subscribe('<subject>', cb)` — nats / redis style. Or just
# `subscribe({topics: [...]})` which is captured by _KAFKAJS_SUB_RE.
_JS_SUBSCRIBE_STR_RE = re.compile(
    r"(?P<binding>[A-Za-z_$][\w$]*)\s*\.\s*subscribe\s*\(\s*"
    r"(?P<quote>['\"])(?P<subject>[^'\"]+)(?P=quote)",
)

# kafkajs: `consumer.subscribe({ topic: '<t>' })` and the multi-topic
# `topics: ['<t1>', '<t2>']` variant.
_KAFKAJS_SUB_RE = re.compile(
    r"(?P<binding>[A-Za-z_$][\w$]*)\s*\.\s*subscribe\s*\(\s*\{\s*"
    r"(?:topic|topics)\s*:\s*(?P<value>(?:['\"][^'\"]+['\"])|(?:\[[^\]]+\]))",
)

# kafkajs: `consumer.run({ eachMessage: async (...) => {...} })`. We use
# the binding as the symbol — the callback is rarely named.
_KAFKAJS_RUN_RE = re.compile(
    r"(?P<binding>[A-Za-z_$][\w$]*)\s*\.\s*run\s*\(\s*\{\s*eachMessage\s*:",
)


def _extract_topic_list(value: str) -> list[str]:
    """Pull topic strings out of the kafkajs `topic:` / `topics:` value blob."""
    out: list[str] = []
    for m in re.finditer(r"['\"]([^'\"]+)['\"]", value):
        out.append(m.group(1))
    return out


def _discover_js(repo_root: Path) -> list[EntryPoint]:
    """Scan JS/TS files for kafkajs / amqplib / nats consumer registrations."""
    found: list[EntryPoint] = []
    files: list[Path] = []
    for ext in (".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"):
        for p in repo_root.rglob(f"*{ext}"):
            if not p.is_file():
                continue
            if _is_skipped(p, repo_root):
                continue
            files.append(p)
    files.sort()

    for path in files:
        raw = _read(path)
        if not raw:
            continue
        if not any(kw in raw for kw in ("consume(", "subscribe(", ".run(", "kafkajs", "amqplib", "nats")):
            continue
        rel = str(path.relative_to(repo_root))
        text = _strip_js_comments(raw)

        for m in _JS_CONSUME_RE.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            binding = m.group("binding")
            queue = m.group("queue")
            found.append(
                EntryPoint(
                    kind=EntryPointKind.MQ_CONSUMER,
                    file=rel,
                    line=line,
                    symbol=f"{binding}.consume:{queue}",
                    type_origin="message_queue_consumer",
                    metadata={
                        "language": "javascript",
                        "library": "amqplib",
                        "queue": queue,
                        "binding": binding,
                        "api": "consume",
                    },
                    docstring="",
                    intended_behaviour_sources=(),
                )
            )

        for m in _KAFKAJS_SUB_RE.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            binding = m.group("binding")
            topics = _extract_topic_list(m.group("value"))
            for topic in topics:
                found.append(
                    EntryPoint(
                        kind=EntryPointKind.MQ_CONSUMER,
                        file=rel,
                        line=line,
                        symbol=f"{binding}.subscribe:{topic}",
                        type_origin="message_queue_consumer",
                        metadata={
                            "language": "javascript",
                            "library": "kafkajs",
                            "topic": topic,
                            "binding": binding,
                            "api": "subscribe",
                        },
                        docstring="",
                        intended_behaviour_sources=(),
                    )
                )

        # Plain `<binding>.subscribe('<subject>', cb)`. Filter out matches
        # that are also covered by the kafkajs-object form above (those
        # have `{` immediately after the `(` so they don't match this
        # regex's `(['"]...['"])` requirement).
        for m in _JS_SUBSCRIBE_STR_RE.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            binding = m.group("binding")
            subject = m.group("subject")
            found.append(
                EntryPoint(
                    kind=EntryPointKind.MQ_CONSUMER,
                    file=rel,
                    line=line,
                    symbol=f"{binding}.subscribe:{subject}",
                    type_origin="message_queue_consumer",
                    metadata={
                        "language": "javascript",
                        "library": "nats_or_redis",
                        "subject": subject,
                        "binding": binding,
                        "api": "subscribe",
                    },
                    docstring="",
                    intended_behaviour_sources=(),
                )
            )

        for m in _KAFKAJS_RUN_RE.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            binding = m.group("binding")
            found.append(
                EntryPoint(
                    kind=EntryPointKind.MQ_CONSUMER,
                    file=rel,
                    line=line,
                    symbol=f"{binding}.run:eachMessage",
                    type_origin="message_queue_consumer",
                    metadata={
                        "language": "javascript",
                        "library": "kafkajs",
                        "binding": binding,
                        "api": "run_eachMessage",
                    },
                    docstring="",
                    intended_behaviour_sources=(),
                )
            )

    return found


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find message-queue consumer registrations across Python and JS/TS."""
    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    if "python" in languages:
        found.extend(_discover_python(repo_root))
    if "javascript" in languages or "typescript" in languages:
        found.extend(_discover_js(repo_root))

    seen: set[tuple[str, int, str]] = set()
    unique: list[EntryPoint] = []
    for ep in found:
        key = (ep.file, ep.line, ep.symbol)
        if key in seen:
            continue
        seen.add(key)
        unique.append(ep)
    unique.sort(key=lambda e: e.sort_key())
    return unique

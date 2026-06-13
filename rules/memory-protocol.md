# CAA memory protocol — recall before acting, index notes by the QUESTION

This is the **code-auditor-agent (CAA)** instance of the AI-Maestro markdown memory
system. The memory system is **{ tool · rule · skills }**: the `memgrep` recall
engine (the tool), this protocol (the rule), and the `caa-memory-recall` /
`caa-memory-write` skills that implement it. It is a curated, symptom-indexed note
corpus in the project's `memory/` dir — distinct from conversation/transcript
search.

Canonical source of the law: `~/.claude/rules/markdown-memory-recall.md` (the
user-global rule). This file parameterises it for the CAA role and points at CAA's
two memory skills.

## The one law: index by the QUESTION/symptom, not the answer's jargon

A note is found from the SYMPTOM, not the solution. When CAA writes a note, its
`description:` (and `title`/`tags`) MUST carry the words a future session will have
when the problem RECURS — the user's words, the error text, the symptom — NOT the
jargon of the fix. Recall ranks on `description + title + tags`; the BODY holds the
answer (two-hop recall: a symptom query lands on the note; the note's body gives the
fix).

- WRONG `description`: "domain-lens findings feed the fixers in scan-and-fix mode".
- RIGHT `description`: "fix mode ignored some findings / domain-lens issues never
  got fixed — why" + the fix fact in the body.

## Recall BEFORE acting (the protocol)

Before debugging a recurring CAA problem, making an engine/lens design decision, or
acting on a recurring failure, RECALL first — "have we hit this before?". Cheap, and
it is the whole point of having a memory. Run the `caa-memory-recall` skill, or
directly:

```bash
# Scope roots, most-specific-first (LOCAL > PROJECT > USER on a conflict):
LOCAL_MEM="$HOME/.claude/projects/$(pwd | sed 's#/#-#g')/memory"      # machine-private
PROJECT_MEM="$(git rev-parse --show-toplevel 2>/dev/null || pwd)/memory"  # git-tracked
USER_MEM="$HOME/.claude/memory"                                       # global
ROOTS=""; for d in "$LOCAL_MEM" "$PROJECT_MEM" "$USER_MEM"; do [ -d "$d" ] && ROOTS="$ROOTS $d"; done

SYMPTOM="the user's words / the error / the symptom"     # NOT the answer's jargon
if command -v memgrep >/dev/null 2>&1; then
  # shellcheck disable=SC2086
  memgrep recall "$SYMPTOM" $ROOTS        # notes ranked best-first: path — description
else
  # shellcheck disable=SC2086
  grep -rliE "$SYMPTOM" $ROOTS 2>/dev/null   # fallback: degrade, never break
fi
```

Read the top 1-3 notes; the answer is in their bodies. If recall returns nothing,
the memory doesn't exist yet — solve it, then write one with `caa-memory-write`.

memgrep is a Rust binary; if `command -v memgrep` is empty the recall skill MUST
fall back to `grep -rliE` so recall **degrades, never breaks**. Install once with
`cargo install --path <ai-maestro-janitor>/tools/memgrep` (puts it on
`~/.cargo/bin`).

## The note schema

```yaml
---
name: <kebab-slug>                 # == filename stem
description: "<symptom surface — the load-bearing recall field, in the QUESTION's words>"
metadata:
  node_type: memory
  type: project | feedback | reference | user
---
<the one fact; for feedback/project follow with **Why:** and **How to apply:** lines.
 Link related notes with [[their-name]] (a link to a not-yet-written note is fine —
 it marks one worth writing later).>
```

Scope routing (UNSURE → LOCAL): **LOCAL** = local paths/usernames/hosts/secrets/
machine-specific (never pushed); **PROJECT** = knowledge any dev on the CAA repo
needs (git-tracked, NO secrets); **USER** = true across all projects. After writing,
add a one-line pointer to that scope's `MEMORY.md` index (`- [Title]({slug}.md) —
hook`).

## What CAA should memorize

Non-obvious, reusable facts: engine/lens design decisions and their WHY, hard-won
debugging gotchas (e.g. the `\b429\b` RL-regex trap, the lensDir-anchoring bug),
confirmed user preferences, project constraints not derivable from the code. Do NOT
memorize what the repo already records (code structure, git history, CLAUDE.md, the
TRDDs) or what only matters to the current conversation.

## Skills

- **`caa-memory-recall`** — symptom → ranked notes (memgrep, grep fallback). Run
  BEFORE debugging/deciding and before writing (so you update the right note).
- **`caa-memory-write`** — capture a durable fact as a schema-valid note + the
  `MEMORY.md` index line, with the `description` carrying SYMPTOM vocabulary.

## Why this exists

Every session otherwise re-derives the same CAA facts (engine invariants, lens
gotchas, prior decisions). Without recall-before-acting + symptom-indexed notes, a
fresh CAA session is blind to the corpus even when the answer was written down last
week. See `~/.claude/rules/markdown-memory-recall.md` for the full recall engine,
the dual-test evaluation method, and the degrade-to-grep contract.

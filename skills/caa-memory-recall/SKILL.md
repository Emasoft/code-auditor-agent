---
name: caa-memory-recall
description: "RECALL — surface prior CAA memory notes by SYMPTOM before debugging a recurring issue or an engine/lens decision; memgrep-ranked with a grep fallback. Triggers: 'recall memories about X', 'did we already solve this', 'have we hit this before'."
version: 4.1.0
author: Emasoft
license: MIT
tags: [memory, recall, memgrep, code-auditor]
effort: high
---

# CAA memory — RECALL

## Overview

The FIND/READ leg of CAA's memory. Run it FIRST — before debugging a recurring
problem, before an engine/lens design decision, before writing a note (so you update
the right note instead of duplicating). Query by the SYMPTOM (the user's words / the
error), never the answer's jargon — the note's author indexed `description` by the
question. See `rules/memory-protocol.md` for the law + schema.

## Instructions

1. **Compose the scope roots** (most-specific-first; on a conflict LOCAL > PROJECT > USER):

   ```bash
   LOCAL_MEM="$HOME/.claude/projects/$(pwd | sed 's#/#-#g')/memory"
   PROJECT_MEM="$(git rev-parse --show-toplevel 2>/dev/null || pwd)/memory"
   USER_MEM="$HOME/.claude/memory"
   ROOTS=""; for d in "$LOCAL_MEM" "$PROJECT_MEM" "$USER_MEM"; do [ -d "$d" ] && ROOTS="$ROOTS $d"; done
   ```

2. **Recall by SYMPTOM** (memgrep when present, else grep — degrade, never break):

   ```bash
   SYMPTOM="the symptom in the user's / the error's words"
   if command -v memgrep >/dev/null 2>&1; then
     # shellcheck disable=SC2086
     memgrep recall "$SYMPTOM" $ROOTS            # ranked best-first: path — description
   else
     # shellcheck disable=SC2086
     grep -rliE "$SYMPTOM" $ROOTS 2>/dev/null    # fallback
   fi
   ```

3. **Read the top 1-3 notes** — the fact is in the body; follow any `[[links]]` into
   related notes. Do NOT dump whole note bodies into the conversation; open the one
   the task needs.
4. **Nothing returned** → the memory doesn't exist yet. Solve the problem, then
   capture it with `caa-memory-write`.

## Output

A short ranked list of `path — description` (memgrep) or matching paths (grep). Read
the few the task needs; never echo full bodies.

## Error Handling

- `memgrep` not on `PATH` → use the `grep -rliE` fallback (recall degrades, never
  blocks). Install once: `cargo install --path <ai-maestro-janitor>/tools/memgrep`.
- No memory dir for a scope → that root is skipped (the `[ -d "$d" ]` test).
- Empty result → report "no prior memory for `<symptom>`"; proceed, and write one after.

## Checklist

- [ ] Scope roots composed (LOCAL/PROJECT/USER, existing only)
- [ ] Queried by the SYMPTOM (the question's words), not the answer's jargon
- [ ] Read only the top notes needed; followed `[[links]]` on demand
- [ ] If empty, flagged it and planned a `caa-memory-write` after solving

## Examples

<example>
User: the engine marked migrations/0429_x.py rate-limited forever — why?
→ recall "rate-limited forever 429 file" → the `\b429\b` RL-regex gotcha note; read its body.
</example>

<example>
User: did we already decide how pr/extended lensSets reuse the agents?
→ recall "pr extended lensSet agentType reuse" → the inline-vs-agentType decision note.
</example>

## Resources

- `rules/memory-protocol.md` — CAA's recall-before-acting law + note schema.
- `~/.claude/rules/markdown-memory-recall.md` — the canonical "index by the QUESTION" rule.
- `caa-memory-write` — the MEMORIZE leg; run RECALL before it.

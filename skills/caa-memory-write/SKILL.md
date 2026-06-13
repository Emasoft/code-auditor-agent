---
name: caa-memory-write
description: "MEMORIZE — capture a durable CAA fact (engine/lens decision, gotcha, constraint, preference) as a schema-valid, symptom-indexed memory note + MEMORY.md index line; recall-first to avoid dupes. Triggers: 'remember this', 'save a memory'."
version: 3.4.4
author: Emasoft
license: MIT
tags: [memory, memorize, write, memgrep, code-auditor]
effort: high
---

# CAA memory — MEMORIZE

## Overview

The CREATE/CAPTURE leg of CAA's memory. Memorize only NON-OBVIOUS, reusable facts —
design decisions + WHY, debugging gotchas, constraints not in the code, confirmed
preferences. NOT what the repo records (code, git history, CLAUDE.md, TRDDs) or
conversation-only detail. See `rules/memory-protocol.md`.

## Instructions

1. **Route the scope** (UNSURE → LOCAL):

   ```bash
   # local = local paths/usernames/hosts/secrets/machine-specific (never pushed)
   # project = knowledge any dev on the CAA repo needs (git-tracked, NO secrets)
   # user = true across ALL projects
   case "$SCOPE" in
     local)   MEMDIR="$HOME/.claude/projects/$(pwd | sed 's#/#-#g')/memory" ;;
     project) MEMDIR="$(git rev-parse --show-toplevel 2>/dev/null || pwd)/memory" ;;
     user)    MEMDIR="$HOME/.claude/memory" ;;
   esac
   mkdir -p "$MEMDIR"
   ```

2. **Recall first — never duplicate.** Run `caa-memory-recall` (or `memgrep recall
   "<subject + symptom>" "$MEMDIR"`) for this fact. If a note already covers it,
   UPDATE that note instead of creating a second one.
3. **Write the note** with the Write tool (not echo) to `"$MEMDIR/<slug>.md"`:

   ```yaml
   ---
   name: <kebab-slug>
   description: "<the SYMPTOM/topic in search words — what a future session will query, NOT the answer's jargon>"
   metadata:
     node_type: memory
     type: project | feedback | reference | user
   ---
   <the one fact — LEAN. For feedback/project add **Why:** and **How to apply:** lines.
    Link related notes with [[their-name]] (a link to a not-yet-written note is fine).>
   ```

4. **Index it.** Append a one-line pointer to `"$MEMDIR/MEMORY.md"` (create if
   missing): `- [Title]({slug}.md) — one-line hook`. Then `memgrep reindex "$MEMDIR"`
   if present (optional).
5. **Sanity-check:** would a future session find this from the SYMPTOM via
   `description`? If it reads like the *answer*, rewrite as the *question*. One
   subject per note.

## Output

The note path + its one-line description. Do NOT echo the whole note back.

## Error Handling

- Secrets/local paths in a PROJECT/USER note → move it to LOCAL (the janitor
  `memory-scope-leak` detector polices this).
- An existing note covers the fact → UPDATE it, don't duplicate.
- `memgrep` absent → recall uses grep; writing still works.

## Checklist

- [ ] Scope routed (local / project / user — unsure → local)
- [ ] RECALL ran first — no existing note already covers this fact
- [ ] Note written: one subject, symptom-indexed `description:`, valid schema
- [ ] `MEMORY.md` index line added (one line, no content duplication)
- [ ] No secrets/local paths in a pushed (project/user) note

## Examples

<example>
Gotcha: a bare /429/ in the RL regex marks files like migrations/0429_x.py rate-limited forever.
→ type: project, LOCAL; description "engine marked a numbered file rate-limited forever — 429 regex".
</example>

<example>
User: remember CAA's lens FPs go to CPV as issues, never devitalized (would degrade the reviewer).
→ type: feedback, PROJECT; description "should I devitalize lens detector-vocabulary findings".
</example>

## Resources

- `rules/memory-protocol.md` — CAA's note schema + scope routing.
- `~/.claude/rules/markdown-memory-recall.md` — the "index by the QUESTION" law.
- `caa-memory-recall` — RECALL: run it BEFORE writing (step 2).

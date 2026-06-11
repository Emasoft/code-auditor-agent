# function-contract lens

## key
function-contract

## fire-when
always (holistic) — but only on files that DEFINE functions/methods (any source file: *.py, *.js, *.ts, *.go, *.rs, *.java, *.rb, *.c, *.cpp, *.cs, *.php, etc.). Prioritize functions that are: high blast radius (≥3 callers); write to a DB / file system / cache / external API / global mutable; reference `tenant_id`, `user_id`, `permission`, `role`, `subscription`, `payment`, `charge` (auth/authz/billing); flagged HIGH_COMPLEXITY / DEEP_NESTING / TOO_MANY_BRANCHES; or are a new public API. Skip pure style/formatting.

## checklist
For each high-risk function defined in this file, walk this 15-question contract protocol; cite file:line evidence for any answer that flags a concern. Layer is `structural`. Severity = MUST-FIX | SHOULD-FIX | NIT; Confidence = HIGH | MEDIUM | LOW (phrase LOW as a question).

Callers & contract:
- Who calls this? List/count every caller.
- What does the contract claim? Restate the docstring/type signature in one sentence.
- Do all callers respect that contract? Check argument shapes against the signature.
- Is the return shape stable — same fields in every code path (early returns, branches, error paths)?
- Does it rename/remove a previously-public symbol? If so, are ALL callers updated?

State & side effects:
- What state does it mutate (DB, cache, file, global, self)?
- Is the mutation idempotent — safe to retry without duplicate/corrupt effects?
- Is the mutation atomic (transaction / lock / compare-and-swap), or can a partial write be observed?
- What ordering assumptions does it make (e.g. calls A before B) — does the caller guarantee that order?

Dependency failure:
- What external calls does it make (network, DB, FS)?
- For each external call, what happens on failure — retry / bubble-up / swallow / fallback? (Silently-swallowed errors are a finding.)
- Does a mid-function failure leave state half-updated (no rollback/compensation)?

Error paths:
- What exceptions/errors can this raise? List them.
- Are callers prepared for those errors? Check each caller's handling.

Duplicates & consistency:
- Does this duplicate existing logic elsewhere in the codebase? If a near-identical implementation exists, flag it (a "new" function re-implementing existing logic is a finding).

Selection note: if a function in this file clearly deserved this deep-dive and you could not cover it, say so — the skipped-but-risky function is itself a finding.

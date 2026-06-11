# architecture-consistency lens

## key
architecture-consistency

## fire-when
always (holistic) — fires per source file in any codebase that already has ≥3 sibling files in the same directory/package/module to establish a local convention. Skip greenfield code with NO established neighbourhood convention. Applies across all languages; especially valuable for polyglot monorepos (e.g. Python + TypeScript sharing cross-process types). Compare the file against its siblings, NOT against universal style ideals.

## checklist
Detect code that "looks reasonable in isolation but is wrong HERE" — i.e. diverges from the established patterns of its surrounding neighbourhood. This is conformance detection, NOT correctness (per-line bugs are out of scope) and NOT style-policing (whether the convention itself is good is out of scope). Every finding MUST cite BOTH the offending code AND the sibling convention it breaks — a bare "this doesn't fit" is not a finding. Category is one of: error-handling | naming | data-shape | layering | polyglot | inheritance | api-shape. Layer is always `structural`.

- Establish the neighbourhood first: sample ≥3 SIBLING files in the same directory (or failing that, the same package/module). A single sibling does NOT establish a convention.
- Error-handling style mismatch: file uses exceptions / `.unwrap()` / panics where siblings consistently use Result types (or vice versa), or return-tuple-of-(value, err) vs errno-style — any divergence from the sibling error idiom.
- Naming-convention deviation: snake_case vs camelCase vs kebab-case; sync vs `_async` suffix; `is_*` vs `has_*` predicates — names not matching the neighbourhood convention.
- Import discipline mismatch: relative vs absolute vs barrel imports differing from how siblings import.
- Data-structure inconsistency: similar data modelled differently from siblings (tuple vs dataclass vs dict vs Pydantic), e.g. some endpoints return a list but this one returns a dict-with-`items` key.
- Layering violation: file crosses a layer boundary the rest of the code respects (e.g. a UI module suddenly imports a DB module directly).
- Inheritance hierarchy oddity: new class inherits from a different base than its siblings do.
- API-surface drift for public functions/classes: argument shape (positional / keyword-only / context object), return shape (raw value / wrapper / Result), doc-string style (Google / NumPy / Sphinx / none), and side-effect discipline (pure / mutates self / mutates global) inconsistent with ≥3 adjacent public siblings.
- File-layout idiom mismatch: one-class-per-file vs module-of-functions differing from the local norm.
- Polyglot cross-process type drift: a cross-language type pair whose fields don't match (e.g. a TypeScript `interface User` whose backing Python `class User` has different field names) — a bug magnet.
- No greenfield false positives: if the file has no siblings (genuinely new domain), do NOT invent a convention to police against.
- Confidence calibration: every finding includes HIGH (direct evidence) / MEDIUM (one hidden assumption) / LOW (phrase as a question — LOW must begin with "May ", "Possibly ", "Verify whether ", or end with "?").
- Severity tiers: MUST-FIX (architectural drift that will create future ambiguity or bugs), SHOULD-FIX, NIT (minor style drift only).

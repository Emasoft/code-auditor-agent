# type-design lens

## key
type-design

## fire-when
A file declares at least one NEW public type. Greppable signals:
- Python: module-level `class `, `@dataclass`, `TypedDict`, `Protocol`, `NamedTuple`, `Enum` whose name does NOT start with `_`.
- TypeScript: `export interface`, `export type`, `export enum`, `export class` (any exported type).
- Go: exported `type ... struct` / `type ... interface` (capital-letter name).
- Rust: `pub struct`, `pub enum`, `pub trait`.
- File extensions: `*.py`, `*.ts`, `*.tsx`, `*.go`, `*.rs`.
Private types (leading `_`, lowercase Go names, non-`pub` Rust) are OUT of scope.

## checklist
For each NEW public type in the file, grade A-F on four dimensions and run the anti-pattern catalogue. The recurring lens is "make illegal states unrepresentable." Cite file:line + snippet for any grade ≤ C. Layer is always `structural`.

- ENCAPSULATION: A=fields private/read-only, mutation via invariant-enforcing methods; C=mostly public fields, invariants only documented not enforced; F=public mutable fields that other code depends on specific values of.
- EXPRESSION OF INTENT: does the NAME + SHAPE communicate the domain concept and forbid invalid combinations? C=generic name (`Data`/`Info`/`Manager`); D=name and shape disagree (e.g. `UserRequest` with no user); F=stringly-typed (`dict[str, Any]`, `Record<string, unknown>`).
- USEFULNESS: count actual call sites. A=≥3 call sites, each uses ≥2 fields, prevents a real bug class; C=1 call site (a typed dict would do); D=ZERO call sites in diff/repo (dead-on-arrival); F=the same type defined twice (duplication).
- ENFORCEMENT: are invariants checked at the BOUNDARY (`__post_init__`/constructor/Pydantic validator/zod schema/`From`-impl) or scattered ad-hoc? D=no enforcement, tests must catch misuse; F=documented invariants are CONTRADICTED by the actual constructor.
- Primitive obsession: `user_id: str` / `int` instead of a nominal type (`UserId`, `NewType`).
- Optional-means-required: `Optional[X]` whose code path ALWAYS sets it.
- Required-but-defaulted: `field(default=...)` callers never override.
- Stringly-typed enum: `status: str` with a fixed value set and no `Enum`.
- Anaemic data class: data with no methods enforcing invariants.
- God class / wide struct: >10 fields mixing multiple domain concerns.
- Erasure type alias: `type X = Any` / `type X = dict` (loses information).
- Mutable default arg: `field(default=[])` / `: list = None`.
- Generic name: `Data`, `Info`, `Manager`, `Helper`, `Util`, `Wrapper`.
- Boolean blindness: `def fn(x: bool, y: bool, z: bool)` instead of an enum.
- Validation outside type: caller-side `assert` for what the type should enforce.
- Make-illegal-states-representable: type permits contradictory state, e.g. `status="active"` alongside `archived_at=now`.
- Confidence on every finding: HIGH (directly supported by code), MEDIUM (one hidden runtime assumption), LOW (phrase as a question — begin "May "/"Possibly "/"Verify whether " or end with "?"). Severities: MUST-FIX / SHOULD-FIX / NIT.

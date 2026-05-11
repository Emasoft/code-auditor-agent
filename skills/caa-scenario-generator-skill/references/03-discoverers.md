# Discoverers catalog

## Table of Contents

- [Discoverer contract](#discoverer-contract)
- [Dispatch](#dispatch)
- [Phase 1 discoverers](#phase-1-discoverers)
- [Adding a new discoverer](#adding-a-new-discoverer)
- [Discoverer outputs by kind](#discoverer-outputs-by-kind)
- [Performance budget](#performance-budget)

## Discoverer contract

Every file in `scripts/scenario_generator/discoverers/<type_name>.py`
exports:

```python
def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    ...
```

Constraints:

- **Deterministic.** Sort all output by `(file, line, symbol)` before
  returning. Two calls on the same repo MUST return identical lists.
- **No LLM.** Regex/AST/configparser only. No subprocess calls to
  language servers; no `curl` to GitHub; no network access. The
  discoverer runs in the orchestrator's turn and must be fast (< 5 s
  on a 10K-file repo).
- **Language gate.** First check: if your language isn't in
  `languages`, return `[]`.
- **No filesystem writes.** Read only. The emit step writes outputs.
- **Universal output.** Populate `EntryPoint` fields from
  `scripts/scenario_generator/types.py`. Set `type_origin` to your
  type name. Use the right `EntryPointKind` from the enum (see ref 02).
- **Skip noise dirs.** Use a `_SKIP_DIRS` frozenset (copy from
  `web_python_fastapi.py`). Always skip `.git`, `node_modules`,
  `__pycache__`, `tests`, `test`, `tests_dev`, `dist`, `build`,
  `target`, `.venv`, `vendor`.

## Dispatch

`scripts/scenario_generator/emit_scenarios_json._load_discoverer` looks
up `scripts.scenario_generator.discoverers.<type_name>` via
`importlib.import_module`. If the module doesn't exist, the engine
falls back to `unknown_software`. Adding a new discoverer = adding a
new file with the right name. **No registration step needed.**

## Phase 1 discoverers

Phase 1 of TRDD-6857f67f §10 ships the 10 most-common discoverers:

| Discoverer | Target type | What it finds |
|---|---|---|
| `web_python_fastapi.py` | web_service_python | `@app.get/post/...`, `@router.get/post/...`, `app.add_api_route(...)`; metadata: method, path, framework, binding; sources: OpenAPI |
| `web_node_express.py` | web_service_node | `app.get/post/...`, `router.get/post/...`; metadata: method, path, framework, binding |
| `web_node_nextjs.py` | web_service_node | File-based routing: `pages/api/*.ts` (pages router) and `app/**/route.ts` (app router) → HTTP routes; `pages/**/*.tsx` and `app/**/page.tsx` → UI routes |
| `cli_python_click.py` | cli_python | `@click.command()`, `@click.group()`, `@<group>.command()`; metadata: command name, is_group, options |
| `cli_node_yargs.py` | cli_node | `.command(...)` string-form and object-form; metadata: command name, options |
| `library_python.py` | library_python | Public top-level callables + `__all__` filtering; skips `_*` and `_internal/`/`_private/` |
| `firmware_arduino.py` | firmware_arduino | `setup()` (BOOT_PATH), `loop()` (MAIN_FUNCTION), `attachInterrupt(...)` (GPIO_INTERRUPT), `Serial.onReceive(...)` etc. (EVENT_LISTENER) |
| `firmware_platformio.py` | firmware_platformio | Parses `platformio.ini` per-env, dispatches to framework-specific sub-extraction (arduino/espidf/stm32cube/mbed/baremetal) |
| `linux_kernel_module.py` | linux_kernel_module | `module_init(...)`, `module_exit(...)`, `file_operations` struct members (ioctl/read/write/...), `EXPORT_SYMBOL(...)` |
| `fpga_verilog.py` | fpga_verilog | Top-level module identified via constraint files (`.xdc`/`.lpf`/`.sdc`); emits one EntryPoint per port (input/output/inout) with direction + width + module name |

Plus `unknown_software.py` (always shipped) — the fallback that finds
`main()` patterns and public top-level callables across 10 languages
(Python, JS, TS, Rust, Go, C, C++, C#, Ruby, Java, Kotlin, Swift).

## Adding a new discoverer

Use `web_python_fastapi.py` as the reference pattern. Steps:

1. **Pick the type name** that matches a row in §3.1.c (in
   `detect_software_type.py`). The file name MUST equal the type name.
2. **Add a fingerprint** to `detect_software_type.py` if one doesn't
   already exist for your type. Test that detection fires on a small
   fixture.
3. **Write the discoverer**:
   - Language gate at top.
   - Deterministic file iteration (sorted glob, SKIP_DIRS).
   - Cheap pre-filter (e.g. `if "fastapi" not in text.lower(): continue`).
   - Regex extraction (no AST — keeps the discoverer fast + portable).
   - Use the right `EntryPointKind` for what you're emitting.
   - Cross-reference docs/specs for `intended_behaviour_sources`.
   - Final dedup + sort.
4. **Build a fixture** under `tests/fixtures/scenario_generator/<type>/`
   exercising every code path the discoverer takes.
5. **Generate goldens**:
   ```
   uv run --no-project python -m scripts.scenario_generator.emit_scenarios_json \
       tests/fixtures/scenario_generator/<type> _gen 20260511_000000+0200
   cp _gen/...-scenarios.json tests/fixtures/scenario_generator/<type>/expected-scenarios.json
   cp _gen/...-detected-types.json tests/fixtures/scenario_generator/<type>/expected-detected-types.json
   rm -rf _gen
   ```
6. **Verify byte-identical determinism** by running step 5 twice into
   different temp dirs and `diff -q` the goldens.
7. **Lint:** `ruff check + ruff format` pass on the discoverer file.
8. **Add the row to ref 03 above.**

## Discoverer outputs by kind

Each discoverer should emit ONE `EntryPoint` per discovered surface
(not one per scenario — the family expansion in
`emit_scenarios_json._make_scenario` multiplies entries by applicable
families). So a FastAPI handler with 3 applicable families becomes
3 scenarios, but only 1 EntryPoint.

Avoid duplicate entries with the same `(file, line, symbol)` triple
in the same discoverer's output; the engine deduplicates across
discoverers but expects each discoverer to be internally clean.

## Performance budget

The discoverers run in series (within the same skill turn). With 9
Phase-1 discoverers, the budget is ~3 s per discoverer on a typical
codebase. Optimize for the cheap-prefilter case: read the file's first
preview, bail if no signal, only then run heavier regex.

Use `CONTENT_PREVIEW_BYTES = 65536` to 131072 — large enough to catch
most routes/handlers, small enough that 10K-file repos don't kill
performance.

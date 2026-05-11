# Unknown software fixture

This fixture exercises the fallback discoverer (`unknown_software.py`)
on a codebase that matches NO specific type fingerprint.

A small Lua script — Lua is not in the §3.1.c registry, so detection
falls through to `unknown_software` and the discoverer extracts what
it can via the generic patterns (no `main()` for Lua, but if there
were one in another language, it would be found).

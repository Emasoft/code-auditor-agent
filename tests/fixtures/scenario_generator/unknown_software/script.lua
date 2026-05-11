-- Tiny Lua script — unknown_software fallback fixture.
-- Lua is not in the §3.1.c registry, so detection falls through to
-- `unknown_software` and the discoverer emits zero scenarios for Lua
-- (no Lua patterns in unknown_software.py). The fixture still serves to
-- prove that `unknown_software` is the only type detected here.

local function greet(name)
  return "hello, " .. name
end

print(greet("world"))

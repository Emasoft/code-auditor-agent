# elixir lens

## key
elixir

## fire-when
*.ex, *.exs files; Elixir/Phoenix codebases (mix.exs present, deps include `:phoenix`, `:ecto`, `:phoenix_live_view`). Content markers: `use GenServer`, `handle_call`/`handle_cast`/`handle_info`, `Supervisor`/`use Supervisor`, `Ecto.Multi`, `Repo.transaction`, `use Phoenix.LiveView`/`mount/3`/`handle_event`, `Phoenix.PubSub`/`subscribe`/`broadcast`, `:code_change`.

## checklist
Apply to ONE Elixir/Phoenix file. Layer is always `structural`. Severities and category names are exact.

- [state-mutation, SHOULD-FIX] GenServer state mutations occur only in `handle_call`/`handle_cast`/`handle_info` — never in `init/1` after start, never in externally-called helper functions.
- [cast-vs-call, SHOULD-FIX] Non-blocking fire-and-forget uses `handle_cast`; blocking operations use `handle_call` with an explicit timeout. Flag misuse either direction.
- [supervisor, SHOULD-FIX] A new worker added to a supervisor uses a restart strategy (`:one_for_one` / `:rest_for_one` / `:one_for_all`) consistent with its siblings' assumptions; flag mismatch.
- [ecto-multi, SHOULD-FIX] Multi-step DB operations run through `Ecto.Multi`, not raw `Repo.transaction(fn -> ... end)` with manual error tracking.
- [liveview-mount, MUST-FIX] `mount/3` runs twice (HTTP then WebSocket), so any side-effect inside `mount/3` is guarded by `connected?(socket)`. Unguarded side-effect = MUST-FIX, no exceptions.
- [liveview-event-auth, MUST-FIX] Every `handle_event` callback validates session/assigns before mutating state. Missing auth check = MUST-FIX, no exceptions.
- [hot-upgrade, SHOULD-FIX] A new module added where the supervisor expects hot-code-upgrade support implements `:code_change/3`.
- [hot-upgrade, NIT] A stateful schema change lacking release notes is a NIT.
- [pubsub-naming, SHOULD-FIX] PubSub topics follow the codebase convention (e.g. `"user:#{id}"`); ad-hoc topic names that break existing listeners are flagged.

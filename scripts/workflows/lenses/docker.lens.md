# docker lens

## key
docker

## fire-when
Dockerfile, Containerfile, `*.dockerfile`, `docker-compose*.yml`, `docker-compose*.yaml`, `compose.yml`, `compose.yaml`; any file whose content begins with/contains `FROM ` directives or compose `services:` blocks.

## checklist
Audit this Dockerfile / Containerfile / compose file for container security and operational hygiene. Cite `file:line` + snippet for every finding; Layer is always `structural`. Use the exact Category names and Severity tiers (MUST-FIX / SHOULD-FIX / NIT) given.

Dockerfile / Containerfile:
- **Non-root USER** (cat: `user`): final `USER` directive sets a non-root user. Missing `USER`, or `USER root` as the effective final user → MUST-FIX.
- **No `:latest` tag** (cat: `tag`): `FROM image:latest` → SHOULD-FIX (reproducibility). A pinned digest `FROM image@sha256:...` is ideal; tag-only is acceptable; `:latest` is not.
- **Pinned base image digest** (cat: `tag`): absence of `@sha256:...` digest pin when only a tag is used → NIT.
- **HEALTHCHECK declared** (cat: `healthcheck`): long-running services without a `HEALTHCHECK` directive → SHOULD-FIX.
- **Multi-stage build** (cat: `multi-stage`): a build stage (compilers, package managers) distinct from the runtime stage; missing for compiled languages → SHOULD-FIX.
- **No secrets in ENV/ARG** (cat: `secrets`): `ENV SECRET=<real value>` or `ARG SECRET=<real value>` with an actual secret value committed → MUST-FIX, regardless of context.
- **No `chmod 777`** (cat: `permissions`): wide-open file permissions → SHOULD-FIX.
- **Minimal layers** (cat: `layers`): excessive separate `RUN` chains that could be combined with `&&` → NIT only.

docker-compose / compose.yaml:
- **No `privileged: true`** (cat: `privileged`): privileged mode → MUST-FIX (security).
- **No `network_mode: host`** (cat: `network`): host networking → SHOULD-FIX.
- **`read_only: true` on app containers** (cat: `permissions`): missing read-only root filesystem → NIT.
- **Minimal capabilities** (cat: `capabilities`): `cap_drop: [ALL]` followed by a minimal `cap_add: [...]`; missing → NIT.

Notes: hadolint covers many Dockerfile checks mechanically — do not re-flag a finding a linter would already produce. Confidence calibration HIGH / MEDIUM / LOW.

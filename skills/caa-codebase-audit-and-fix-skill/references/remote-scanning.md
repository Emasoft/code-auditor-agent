# Remote Repository Scanning

## Table of Contents
- [Local Clone Method](#local-clone-method)
- [API-Only Method](#api-only-method)

## Local Clone Method

For auditing a GitHub repo without a local clone:
1. Shallow clone: `gh repo clone {owner}/{repo} -- --depth=1 /tmp/caa-audit-{repo}`
2. Set `SCOPE_PATH` to the clone directory
3. Run standard Phase 0-8 pipeline
4. After final report is saved to `REPORT_DIR`, cleanup: remove the clone directory

## API-Only Method

For GitHub repos accessible via API only (no clone):
1. Use `gh api repos/{owner}/{repo}/git/trees/HEAD?recursive=1` to get file inventory
2. Use `gh api repos/{owner}/{repo}/contents/{path}` to read individual files
3. This is slower but avoids disk usage for very large repos

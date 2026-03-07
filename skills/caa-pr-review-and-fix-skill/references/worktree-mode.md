# Worktree Mode

## Table of Contents

- [How It Works](#how-it-works)
- [Prerequisites for Worktree Mode](#prerequisites-for-worktree-mode)
- [When NOT to Use Worktrees](#when-not-to-use-worktrees)

When `USE_WORKTREES=true`, agents run in isolated git worktrees via `isolation: "worktree"` in the Agent tool. This is useful for large PRs with many domains where concurrent agents might otherwise see each other's in-progress changes.

## How It Works

1. **Before spawning**, resolve `ABSOLUTE_REPORT_DIR = $(pwd)/docs_dev/` (or `$(pwd)/{REPORT_DIR}` if custom). All agents write reports to this absolute path so reports are accessible from the main worktree after agent completion.

2. **Review agents** (Phase 1-4, dedup): Each gets a clean, isolated snapshot of the repo. They read code from their worktree but write reports to the main `REPORT_DIR`. Since they make no code changes, worktrees are auto-cleaned after completion.

3. **Fix agents** (Procedure 2): Each gets an isolated worktree on a separate branch. They modify code in their worktree and write reports to the main `REPORT_DIR`. After ALL fix agents complete, the orchestrator merges their branches back to the current branch sequentially:
   ```
   for each completed fix agent worktree:
     git merge --no-edit {worktree_branch}
     # If merge conflict: resolve manually or escalate to user
   ```

4. **Spawning pattern addition**: When USE_WORKTREES is true, add `isolation: "worktree"` to every Task() call. The agent prompt must include `REPORT_DIR: {ABSOLUTE_REPORT_DIR}` so the agent writes reports outside its worktree. See `procedure-1-review.md` and `procedure-2-fix.md` in the references directory for the complete spawning patterns with worktree support.

## Prerequisites for Worktree Mode

- Git repository must be in a clean state (no uncommitted changes)
- Sufficient disk space for N worktree copies (one per concurrent agent)
- The `REPORT_DIR` must be an absolute path accessible from all worktrees

## When NOT to Use Worktrees

- Small PRs with 1-3 domains (overhead outweighs benefit)
- When disk space is limited
- When agents don't modify code (review-only mode with `caa-pr-review-skill`)

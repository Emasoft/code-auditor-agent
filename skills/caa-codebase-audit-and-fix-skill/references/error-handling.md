# Error Handling

## Table of Contents
- [Recovery Strategies](#recovery-strategies)

## Recovery Strategies

- **Agent failure**: Check if the output file exists and is complete. If yes, use it. If not, re-spawn with a new UUID but the same agent prefix.
- **Context compaction**: Read the manifest at `{PIPELINE_TS}-caa-manifest-R{RUN_ID}.json` (the orchestrator recorded the full path as `MANIFEST` at pipeline start; if that memory is gone, glob `*-caa-manifest-R{RUN_ID}.json` — RUN_ID uniquely identifies one file per run) to recover full pipeline state after context compaction.
- **Partial runs**: The manifest tracks per-file completion status. Resume from the last incomplete phase.
- **Checkpoint recovery (Phase 6)**: Each fix agent writes a checkpoint JSON after every fix. On failure, the replacement agent reads the checkpoint and continues from the last successful fix.
- **Escalation**: After 3 retries on the same agent task, escalate to the orchestrator for manual intervention.

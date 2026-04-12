# Agent Recovery Protocol

## Table of Contents

- [Failure Modes & Detection](#failure-modes--detection)
- [Step 1: Detect the Loss](#step-1-detect-the-loss)
- [Step 2: Verify the Loss](#step-2-verify-the-loss)
- [Step 3: Clean Up Partial Artifacts](#step-3-clean-up-partial-artifacts)
- [Step 4: Re-Spawn the Task](#step-4-re-spawn-the-task)
- [Step 5: Record the Failure](#step-5-record-the-failure)
- [Special Cases](#special-cases)
  - [Lost during context compaction](#lost-during-context-compaction)
  - [Agent wrote report with wrong pass number (version/cache collision)](#agent-wrote-report-with-wrong-pass-number-versioncache-collision)
  - [Multiple correctness agents for the same domain (domain label collision)](#multiple-correctness-agents-for-the-same-domain-domain-label-collision)
  - [Test runner left no report but tests actually ran](#test-runner-left-no-report-but-tests-actually-ran)
- [Agent Recovery Checklist](#agent-recovery-checklist)

Protocol for recovering from agent failures during the review-and-fix pipeline. Applies to ALL
agents: correctness swarm, claim verification, skeptical review, security review, dedup, fix agents, and test runner.

## Failure Modes & Detection

| Failure Mode | Detection Signal |
|---|---|
| **Crash / OOM** | Task tool returns error, empty result, or agent process dies mid-execution |
| **Out of tokens** | Agent returns truncated output, `[MAX TURNS]`, or incomplete report file |
| **API errors** | Agent returns "overloaded", rate limit (429), server error (500), or auth failure |
| **Connection errors** | Task tool hangs then returns timeout or network error |
| **Timeout** | Agent does not return within deadline (correctness/claims/skeptical/security agents: 10 min, fix agents: 15 min, test runner: 20 min, consolidation/domain-auditor/verification/todo-generator/fix-verifier agents: 3 min) |
| **Lost during compaction** | Orchestrator's context was summarized; agent task ID no longer in memory and no result was ever received |
| **Broken reference** | TaskGet returns error or "agent not found" |
| **ID collision** | Two agents wrote to overlapping filenames (prevented by UUID filenames -- verify if suspected) |
| **Version collision** | Agent used stale plugin/agent definition cached from a prior session; writes wrong format or wrong pass prefix |

## Step 1: Detect the Loss

The orchestrator MUST mentally track every spawned agent with these fields:

```
taskId:        string    // Task tool's returned ID
agentType:     string    // "correctness" | "claims" | "skeptical" | "security" | "dedup" | "fix" | "test" | "consolidation" | "domain-auditor" | "verification" | "todo-generator" | "fix-verifier"
domain:        string    // Domain label (e.g., "governance-core") or "N/A" for single agents
outputPath:    string    // Expected report file path (with UUID)
findingPrefix: string    // e.g., "CC-P3-A2" -- for re-spawn consistency
launchedAt:    timestamp // When the agent was spawned
status:        string    // "running" | "done" | "failed" | "lost"
```

An agent is **LOST** if ANY of these are true:

- Task tool returned an error, empty string, or exception
- Agent returned a result but its expected output file does not exist
- Agent returned but its output file is incomplete (see Step 2)
- Agent's task ID cannot be resolved (TaskGet returns error)
- Agent has been running longer than its deadline without returning
- Context compaction occurred and the agent's task ID is no longer in the orchestrator's working memory

## Step 2: Verify the Loss

Before cleanup, verify that the agent truly failed (not just slow or communication-disrupted):

1. **Check if output file exists** at the expected `outputPath`
2. **If file exists, check completeness:**
   - File size > 0 bytes
   - File contains the `## Self-Verification` section (the agent's checklist)
   - File does not end mid-sentence or with an unclosed code block
   - File has valid markdown structure matching the agent's output format
3. **If file is COMPLETE** -> the agent finished its work despite the communication failure.
   Mark as "done" and use the file. No re-spawn needed.
4. **If file is INCOMPLETE or MISSING** -> the agent truly failed. Proceed to Step 3.

## Step 3: Clean Up Partial Artifacts

Delete ONLY the lost agent's artifacts. NEVER touch files from other agents or other passes.

```bash
# Identify the lost agent's output file by its UUID
LOST_FILE="reports_dev/code-auditor/caa-correctness-P3-a1b2c3d4.md"

# Verify it belongs to the lost agent (filename contains the UUID assigned to that agent)
# Then delete the partial file
rm -f "$LOST_FILE"
```

**Cleanup rules:**

- Delete partial report files (missing Self-Verification section at the end)
- Delete zero-byte files created by the lost agent
- Delete files with incomplete markdown (unclosed code blocks, truncated mid-sentence)
- **NEVER** delete files from a different agent (different UUID in filename)
- **NEVER** delete files from a different pass (different `P{N}` prefix)
- **NEVER** delete the intermediate merge report or final report from a completed phase
- If unsure whether a file belongs to the lost agent, **leave it** -- the merge script and dedup agent handle extras gracefully

**Fix agent special case -- uncommitted source changes:**

If a fix agent crashed AFTER editing source files but BEFORE the orchestrator committed:

1. Run `git diff` to see what the lost agent changed
2. Run `git stash` to save the partial changes safely
3. Re-spawn the fix agent from scratch (Step 4) -- it will re-read the original files and apply its own fixes
4. After the replacement fix agent succeeds and the orchestrator commits, drop the stash: `git stash drop`
5. **NEVER** commit partial fix agent changes -- they may be incomplete and introduce bugs

## Step 4: Re-Spawn the Task

Create a NEW agent with a NEW UUID for the exact same task:

1. **Generate a new UUID** for the replacement agent's output filename
2. **Copy the original prompt EXACTLY** -- same domain, same files, same finding ID prefix, same pass number
3. **Update only the output path** to use the new UUID
4. **Spawn the replacement agent**

**Re-spawn rules:**

- Always use a **NEW UUID** (prevents filename collision with the deleted partial file)
- Use the **SAME finding ID prefix** (ensures finding ID continuity for the domain)
- Use the **SAME pass number** (the replacement is part of the same pass, not a new pass)
- If the same task fails **3 consecutive times**, **STOP** and escalate to the user:
  ```
  "Agent {type} for domain {domain} failed 3 times.
   Last error: {error_summary}.
   Manual intervention required."
  ```
- Between retries, wait **30 seconds** (API rate limit cooldown, transient error recovery)
- For fix agents: verify `git status` is clean before re-spawning (Step 3 cleanup must be complete)

## Step 5: Record the Failure

Append an entry to the recovery log in the pass audit trail (either in the merged report or
a separate `reports_dev/code-auditor/caa-recovery-log-P{N}.md` file):

```markdown
### Agent Recovery Log

| Time | Agent Type | Domain | Failure Mode | Lost File | Action Taken |
|------|-----------|--------|-------------|-----------|-------------|
| 14:23 | correctness | governance-core | timeout (12 min) | P3-a1b2c3d4.md (0 bytes, deleted) | Re-spawned -> P3-e5f6g7h8.md |
| 14:25 | fix | api-routes | API 429 | P3-i9j0k1l2.md (partial, deleted) | 30s cooldown -> re-spawned |
| 14:40 | test | N/A | OOM | P3-m3n4o5p6.md (missing) | Re-spawned |
```

## Special Cases

### Lost during context compaction

The orchestrator's context was summarized and one or more agent task IDs were lost.

1. Read the agent manifest file: `reports_dev/code-auditor/caa-agents-P{N}-R{RUN_ID}.json`
   - This file records all spawned agents, their domains, prefixes, and expected outputs
   - It survives context compaction because it's on disk
2. For each agent in the manifest, check if its output file exists and is complete
   - File exists and has `## Self-Verification` section -> agent completed successfully
   - File exists but incomplete -> agent died mid-execution (Step 3 cleanup)
   - File missing -> agent never wrote output (re-spawn needed)
3. If the manifest file itself was lost (extreme case), fall back to glob-based recovery:
   - List ALL `caa-*-P{N}-R{RUN_ID}-*.md` files in `reports_dev/code-auditor/`
   - Read first 5 lines of each to identify domain from the report header
   - Cross-reference with the expected domain list
4. For each truly missing report: re-spawn from scratch (Step 4)
5. For fix agents: check `git log` for the most recent fix commit -- if fixes were already committed, the fix agent completed successfully even though its task ID was lost
6. For fix agents: also check checkpoint file `reports_dev/code-auditor/caa-checkpoint-P{N}-R{RUN_ID}-{domain}.json` to see which findings were already resolved

> **Note (Claude Code 2.1.69+):** Resuming after compaction no longer produces a preamble recap. The agent simply continues from where it left off. Recovery steps remain the same — read the manifest to restore pipeline state.

### Agent wrote report with wrong pass number (version/cache collision)

If an agent writes a report with `P2` instead of `P3` (stale prompt from a cached agent definition):

1. The merge script's glob `caa-*-P{N}*.md` will correctly EXCLUDE it (it won't match the current pass)
2. Check if the content is actually from the current pass (correct files audited, correct finding prefixes)
3. If content is correct but filename is wrong: rename the file to the correct pass prefix
4. If content is from a genuinely different pass: delete it and re-spawn

### Multiple correctness agents for the same domain (domain label collision)

UUID filenames prevent file-level collision. But if two agents were accidentally given the same domain:

1. Both will produce separate UUID-named files -- no file collision occurs
2. The merge script will concatenate BOTH files into the intermediate report
3. The dedup agent will handle any duplicate findings between them
4. Note the duplication in the recovery log, but no data loss occurs

### Test runner left no report but tests actually ran

If the test runner crashed after running tests but before writing its report:

1. Check the test command's exit code from the shell (if available in bash history)
2. Check for test runner output in stdout/stderr (the Task tool may have captured partial output)
3. Check for test framework artifacts (e.g., `junit.xml`, `.vitest-result.json`, coverage reports)
4. If evidence shows tests passed: note this in the audit trail and proceed
5. If unclear: re-run the test suite (tests are read-only and idempotent -- safe to re-run)

---

## Agent Recovery Checklist

Copy this checklist and track your progress:

- [ ] Failure detected: agent type, domain, and failure mode identified
- [ ] Loss verified: output file checked for existence and completeness
- [ ] If file complete: marked as done, no re-spawn needed
- [ ] If file incomplete/missing: partial artifacts cleaned up
- [ ] For fix agents: `git diff` checked and partial changes stashed if present
- [ ] Replacement agent spawned with new UUID, same prompt and finding prefix
- [ ] Recovery log entry written to `reports_dev/code-auditor/caa-recovery-log-P{N}.md`
- [ ] If 3 consecutive failures: escalated to user

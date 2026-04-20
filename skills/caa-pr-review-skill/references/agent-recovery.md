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
  - [Agent wrote report with wrong pass number](#agent-wrote-report-with-wrong-pass-number-versioncache-collision)
  - [Multiple correctness agents for the same domain](#multiple-correctness-agents-for-the-same-domain-domain-label-collision)
- [Agent Recovery Checklist](#agent-recovery-checklist)

This protocol applies to ALL agents spawned by the orchestrator: correctness swarm, claim verification,
skeptical review, security review (caa-security-review-agent), and dedup agent. When an agent is lost for any reason, the orchestrator MUST follow
these steps to ensure the task is completed and no corrupt artifacts remain.

## Failure Modes & Detection

| Failure Mode | Detection Signal |
|---|---|
| **Crash / OOM** | Task tool returns error, empty result, or agent process dies mid-execution |
| **Out of tokens** | Agent returns truncated output, `[MAX TURNS]`, or incomplete report file |
| **API errors** | Agent returns "overloaded", rate limit (429), server error (500), or auth failure |
| **Connection errors** | Task tool hangs then returns timeout or network error |
| **Timeout** | Agent does not return within deadline (correctness/claims/skeptical/security agents: 10 min, dedup agent: 5 min) |
| **Lost during compaction** | Orchestrator's context was summarized; agent task ID no longer in memory and no result was ever received |
| **Broken reference** | TaskGet returns error or "agent not found" |
| **ID collision** | Two agents wrote to overlapping filenames (prevented by UUID filenames -- verify if suspected) |
| **Version collision** | Agent used stale plugin/agent definition cached from a prior session; writes wrong format or wrong pass prefix |

## Step 1: Detect the Loss

The orchestrator MUST mentally track every spawned agent with these fields:

```
taskId:        string    // Task tool's returned ID
agentType:     string    // "correctness" | "claims" | "skeptical" | "security" | "dedup" | "consolidation" | "domain-auditor" | "verification" | "todo-generator" | "fix" | "fix-verifier"
domain:        string    // Domain label (e.g., "governance-core") or "N/A" for single agents
outputPath:    string    // Expected report file path (with UUID)
findingPrefix: string    // e.g., "CC-P1-A2" — for re-spawn consistency
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
LOST_FILE="reports/code-auditor/caa-correctness-P1-a1b2c3d4.md"

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

## Step 5: Record the Failure

Append an entry to the recovery log (either in the merged report or
a separate `reports/code-auditor/caa-recovery-log-P{N}.md` file):

```markdown
### Agent Recovery Log

| Time | Agent Type | Domain | Failure Mode | Lost File | Action Taken |
|------|-----------|--------|-------------|-----------|-------------|
| 14:23 | correctness | governance-core | timeout (12 min) | P1-a1b2c3d4.md (0 bytes, deleted) | Re-spawned -> P1-e5f6g7h8.md |
| 14:25 | claims | N/A | API 429 | P1-i9j0k1l2.md (partial, deleted) | 30s cooldown -> re-spawned |
```

## Special Cases

### Lost during context compaction

The orchestrator's context was summarized and one or more agent task IDs were lost.

1. List ALL `caa-*-P{N}-*.md` files in `reports/code-auditor/` for the current pass number
2. Build the expected agent roster: which domains should have correctness reports? Was claims run? Was skeptical run? Was dedup run?
3. For each expected report that is missing: check if a complete file exists under a different-than-expected UUID (the agent may have written it but the ID was lost)
4. For each truly missing report: re-spawn from scratch (Step 4)

> **Note (Claude Code 2.1.69+):** Resuming after compaction no longer produces a preamble recap. The agent simply continues from where it left off. Recovery steps remain the same — read the manifest to restore pipeline state.

### Agent wrote report with wrong pass number (version/cache collision)

If an agent writes a report with `P2` instead of `P1` (stale prompt from a cached agent definition):

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

## Agent Recovery Checklist

Copy this checklist and track your progress:

- [ ] All spawned agents are tracked with taskId, agentType, domain, outputPath, findingPrefix, launchedAt, status
- [ ] Lost agents are detected via output file verification (not just task tool response)
- [ ] Partial artifacts are cleaned up before re-spawning
- [ ] Re-spawned agents use NEW UUID but SAME finding prefix and pass number
- [ ] Failed agents are retried up to 3 times with 30s cooldown
- [ ] Failures are recorded in the recovery log
- [ ] Context compaction recovery checks for complete files under unexpected UUIDs

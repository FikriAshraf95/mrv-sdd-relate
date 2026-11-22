# Run parallel subagents on one milestone

> **For:** orchestrators (people or Claude Code sessions) who want several workers on one milestone at once.

Parallel work is safe because every claim and every checkbox edit goes through the daemon's single write queue. Two agents can't win the same task, and their ticks can't overwrite each other (benchmark: 0 double claims and 0 lost ticks across 5 runs of 10 agents, against 139 lost ticks when agents edit the Markdown directly). What you still have to avoid is **two agents editing the same code**.

## Steps

1. **Start the session** (orchestrator name `opus-orch`):

   ```
   what_changed(since="last_session", agent="opus-orch")
   status(agent="opus-orch")
   next_tasks(milestone="M05a", agent="opus-orch")
   ```

2. **Read `overlaps` on each task.** `next_tasks` returns claimable tasks in order. Each has an `overlaps` list: tasks **claimed right now** that share a governing section or a mentioned file with it. A non-empty `overlaps` means running both at once may conflict.

   ```json
   {"id": "M05a.3", "title": "Tell the promoted member by message", "governed_by": ["SPEC-05#2"],
    "overlaps": [{"id": "M05a.2", "claimed_by": "sonnet-2"}]}
   ```

3. **Launch one subagent per task with no overlaps.** Give each a **fixed name** (`sonnet-1`, `sonnet-2`, …) and its task ID, and tell it to follow the worker protocol in `.claude/skills/sdd/SKILL.md`. A prompt that works:

   > Launch subagents in parallel, one per claimable task from `next_tasks` that has an empty `overlaps`, at most 3. Name them `sonnet-1`, `sonnet-2`, `sonnet-3`. Tell each: "Your agent name is `<name>`. Your task is `<id>`. Follow the worker protocol in .claude/skills/sdd/SKILL.md: `what_changed`, `claim_task`, `get_context`, build and test, `log_deviation` for any departure, commit naming the task, `complete_task` with notes, files_touched and commit, then report."

4. **Each worker claims first.** If two workers are pointed at the same task by mistake, one gets `already_claimed` and should report back instead of working on it.

5. **Review as results come in.** `complete_task` returns `unblocked`: tasks that just became claimable. Call `next_tasks` again and launch the next wave.

6. **Handle failures.** A worker that crashed or gave up still holds its claim. Free it at once with `release_task(task_id, agent="opus-orch", force=true)` and relaunch ([details](free-a-stuck-claim.md)).

7. **Close the milestone** when every task is done and acceptance is verified:

   ```
   complete_milestone("M05a", agent="opus-orch", verification="pytest -q green; acceptance 1–2 checked by hand")
   ```

   It fails with `milestone_incomplete` (listing the open tasks) if any task isn't done.

## Tips

- **Use the same names every session.** `what_changed(since="last_session")` and claims follow the name, not the connection. Claude Code subagents share their parent's MCP connection, so the name is the only identity.
- **Watch the Board** at `http://localhost:8770` to see who holds what.
- **Commit per task** and name it: `feat: promote the oldest entry [M05a.2]`. The git sync then links the commit to the task (`COMPLETES`) and the files it changed (`TOUCHES`), so later packets and `explain` can show them.
- **Order with `(after …)`**, not with instructions. `next_tasks` won't offer a task whose `(after …)` tasks aren't done, so the waves come out right by themselves.
- **Conflicting work** that `overlaps` can't see (two tasks that happen to edit one file nobody mentioned) still needs judgement. Mention the files in the task lines (`` `src/booking/cancel.py` ``) to make the overlap visible.
- **Two parallel deviations** get consecutive numbers (D007 and D008). The number is chosen inside the write job, so they never collide.

---
name: done
description: End-of-session status check. Answers "are we done here?" with a verdict on whether the session can be closed, plus everything still open — PRs and their live state, issues filed, follow-ups never filed, tasks waiting on the human, loops still running. Use for /done, "are we done", "all PRs merged?", "what's left", "wrap up", "status?", or before closing an agent session.
---

# Are we done?

The operator runs many sessions at once and reads this one in seconds.
Report **state, not the story**. Short output is the whole point.

## 1. Inventory: from this session

Scan the whole conversation, including any compaction summary. List:

- every PR opened, pushed to or babysat (number + branch)
- every issue filed or commented on
- follow-ups that came up but were **never filed**: bugs found along the way,
  deferred cleanup, "out of scope" notes, flaky tests
- things only the human can do: approvals, secrets, console clicks, device or
  real-money checks, decisions you asked about that got no answer
- anything still running: `/loop`, crons (`CronList`), Monitors, background
  shells, subagents, deploys, workflow runs
- local leftovers: worktrees and branches this session created

Inventory only what this session touched. Leave other sessions' PRs out.

## 2. Verify: read live state, never recall it

Your memory of a PR's state is stale by definition. Fetch it, in one parallel
batch:

```sh
gh pr view N --json number,title,state,isDraft,reviewDecision,statusCheckRollup --jq '{n:.number,t:.title,state:.state,draft:.isDraft,review:.reviewDecision,fail:[.statusCheckRollup[]|select((.conclusion//.state)|IN("FAILURE","ERROR","TIMED_OUT","CANCELLED"))|(.name//.context)],pending:([.statusCheckRollup[]|select(.status=="IN_PROGRESS" or .status=="QUEUED" or .state=="PENDING")]|length)}'
gh issue view N --json number,state,title
git status --porcelain; git log --oneline @{u}.. 2>/dev/null   # uncommitted / unpushed
git worktree list
```

If you cannot verify something, mark it `?`. Do not guess.
A merged PR is not always shipped. If the task needed a deploy, a migration
or a live proof, check whether that happened.

## 3. Report

Use this exact shape. **Leave out any line that has nothing in it.**
One item per `·`. Use numbers and names, not adjectives. Cap: 10 lines.

```
<verdict>
PRs      #412 merged · #413 open, CI ✗ lint · #414 green, awaiting review
Issues   #420 filed (websocket reconnect storm)
Unfiled  stale fixture map (scripts/seed.ts:42) · flaky upload test
You      approve #398 · rotate staging API token
Running  /loop babysitting #413 (next tick ~20m)
Local    2 uncommitted files in wt/feat-x · worktree wt/feat-x unremoved
Next     <the one action you'd take if told "go">
```

The verdict line is one of:

- `✅ Done. Safe to close.` Everything merged or closed, nothing unfiled,
  nothing running, nothing waiting on the human. Print **only** this line.
- `⏳ Not done: <blocker>` Work the agent still owes.
- `👤 Waiting on you: <what>` Only the human can unblock it.

**Closing loses whatever is unfiled, uncommitted or running.** If any of those
exist, the verdict is never ✅.

## Rules

- Never narrate what was done or how. A PR's title is all the history needed.
- Read-only. Don't merge, file, push or clean up. `Next` offers it, and the
  operator says go.
- Each `Unfiled` item gets enough to file it later without this session:
  a `file:line` or the error text, a few words.

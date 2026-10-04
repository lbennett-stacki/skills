---
name: splice-pr
description: Split one large PR or branch into a small stack (or set of parallel branches) of smaller PRs that each review and deploy safely, by copying the original's own files and hunks, never rewriting code. Use for /splice-pr, "split this PR", "break this branch up", "this PR is too big to ship in one go", "stack this", "can we land this in pieces", or when a PR mixes a migration, a refactor and a behaviour change and deploying it all at once feels risky, even if the user doesn't say "splice".
---

# Splice a PR

Turn one oversized PR into two to four smaller ones that land in a safe order.
The slices are cut *from* the original: whole files copied as exact blobs, or
the original's own hunks applied as-is. No code is retyped, reformatted or
"tidied along the way". That is the point of the skill. The author's intent
survives intact, and anyone can prove that the slices add up to the original
byte for byte.

The payoff is risk, not tidiness. Each slice gets a review focused on one kind
of change, and deploys on its own, so a bad deploy points at a small diff and
reverts cleanly. Every extra slice also costs a PR, a review and a deploy, so
cut only where a seam buys something specific.

`scripts/splice.py` (next to this file) does the mechanical work:

| Command | What it does |
| --- | --- |
| `inventory` | Lists changed files, categories, hunk ids and dependency hints |
| `build` | Turns a `plan.json` into commits and verifies them, then creates branches |
| `restack` | Moves the remaining slices onto main after one squash-merges |

It never touches the working tree or the user's index. Run it from inside the
repo:

```bash
SPLICE=<this skill's base directory>/scripts/splice.py
```

## 1. Resolve the target

- **PR number or URL:** run `gh pr view <n> --json number,title,body,url,headRefName,baseRefName,additions,deletions,changedFiles,commits`,
  then `git fetch origin <headRefName> <baseRefName>`. Head is `origin/<headRefName>`, base is `origin/<baseRefName>`.
- **Branch:** head is the branch. Base is `origin/main` unless the user says otherwise. Fetch first.

Read the PR description and the commit list. Together they state the intent,
and clean commit history often already marks the natural seams.

## 2. Inventory

```bash
python3 $SPLICE inventory --base origin/main --head <head> --json <scratch>/inventory.json
python3 $SPLICE inventory --base origin/main --head <head> --hunks path/a.py path/b.ts   # hunk ids, only when a file might need splitting
```

The dependency hints ("A -> B [symbol]") mean a file's added lines use a
symbol or module that the diff adds in another file. That is a strong hint A
cannot land before B. They are heuristic: read the evidence and don't treat
them as proof either way.

Read `learnings.md` (next to this file): seams, constraints and checks that
past runs found worth remembering.

Read the repo's deploy rules before designing: `AGENTS.md`, `CLAUDE.md`,
`CONTRIBUTING.md` and any deploy docs. They decide which orders are safe.
Typical rules look like:

- Rolling deploys run old and new code against the same DB, so changes follow Expand, then Migrate, then Contract.
- A PR carries at most one migration.
- The frontend rolls after the backend.
- Some paths need a changelog fragment in every PR that touches them.
- A checked-in dependency or package graph has to match the imports in each slice.

## 3. Decide whether to split at all

"Don't split" is a valid answer, and often the right one. Recommend leaving
the PR whole when:

- it is under roughly 400 changed lines of non-test, non-generated code;
- it is one behaviour change plus its tests;
- it is docs only; or
- its parts can't stand alone without new code.

Say why, and suggest the cheaper fix instead: a better description, reviewer
notes, `/code-review` on the risky files, or reordering the commits.

Split when the PR mixes risk classes that fail in different ways, or when one
deploy would change several things at once:

- schema with code;
- a mechanical refactor with a behaviour change;
- backend with frontend;
- two independent features;
- a new module with the switch that turns it on.

## 4. Design the slices

Look for seams in this order. Earlier seams are cheaper and safer to land
first:

1. **Schema / migration (expand).** Additive DDL goes first, on its own, so it deploys before any code reads it.
2. **Mechanical changes.** Renames, moves, extracted helpers and formatting, with no behaviour change. The reviewer can skim these, and they shrink every later diff.
3. **Dormant code.** New modules, functions, config or flags that nothing calls yet. They deploy as a no-op, so review can focus on correctness without deploy risk.
4. **The switch.** Wiring, routing, the changed call sites and the flag flip. This is where production behaviour changes. Keep it as small as the code allows, because it gets the closest review and the closest watching after deploy.
5. **Surface.** Frontend or client work that needs the backend already live.
6. **Contract / cleanup.** Removing the old path. It goes last, and in a separate deploy from the switch when the repo's rules call for that.

Each slice has to meet these constraints:

- **Stands alone.** A slice may use only what exists in its parent chain. `build` flags forward references it can detect. Imports, types and generated files still need a check (step 6).
- **Safe to deploy alone** under the repo's rules. No slice may leave production in a state the next deploy has to rescue.
- **Tests travel with the code they test.** A reviewer needs them side by side, and a test can't land before its subject.
- **Generated files travel with their source:** lockfiles, API clients, package graphs, snapshots.
- **Cut at file boundaries where you can.** Take specific hunks only when one file genuinely holds two seams. When a hunk won't separate cleanly, move the boundary rather than edit code.

**Sequential or parallel.** Slices that don't depend on each other get `"after": null`
and go straight off base. They review, merge and deploy in any order, which
beats a longer chain. Chain slices only where there is a dependency edge.

A final slice with several parents can't open as a PR against a single base
without showing its parents' changes. If the parallel slices are small, chain
them instead. Otherwise, say in the plan that the final opens once its parents
land, after a restack onto main.

**How many.** Two or three is typical, and four is plenty. Before adding a
slice, name what it buys: a different reviewer focus, a separate deploy, or an
independent revert. If the answer is "it's neater", fold it into a neighbour.

**The final slice is a fresh PR.** Whatever no slice claims becomes the last
slice, on its own new branch, and it gets its own review. The original branch
and PR stay exactly as they are, as the reference.

**Each slice is its own unit of work.** A reviewer, or someone reading `git log`
a year from now, should see a normal change that does one thing, not a fragment
of a bigger PR. So a slice's branch name, commit message and PR description say
what that slice does and why, in the repo's usual style. Leave out anything
about how it came to exist: no "split from #123", "part 2/3", "slice",
"splice", "stack" or "follow-up to the big PR". If a slice can't be described
as a sensible change on its own terms, the seam is in the wrong place. The only
cross-reference is the ordinary dependency note any PR would carry ("Depends on
#<PR>").

**No new code.** The plan contains only what the original contains. If a seam
truly can't stand without a line the original lacks (a flag default, a
re-export), don't hide it. Offer it as an explicit exception in the plan with
the exact lines, and only on the user's OK carry it as a `glue` patch. The
build labels it `[GLUE]`, and the final slice still restores the original tree,
so the glue disappears by the end. Moving the seam is almost always better.

## 5. Present the plan and stop

Show this, then wait for the user's OK before building anything:

```markdown
## Splice plan for #<n>: <title>
Original: +A −D across F files. Recommendation: <split into N | don't split>, because <one line>.

| # | PR title (as it will appear) | Branch | Based on | Contents | Size | Review focus | Deploy watch | Revert alone? |
|---|------------------------------|--------|----------|----------|------|--------------|--------------|---------------|
| 1 | feat(db): add a nullable x column to thing | you/thing-x-column | main | migrations/…, shared/schema/… | +40 | migration is additive; defaults | migration step, lock time | yes |
| 2 | feat(search): add an x reader | you/x-reader | 1 | shared/services/x/*, tests | +300 | logic correctness; no callers yet | none (no-op) | yes |
| 3 | feat(search): rank by x | you/search-reads-x | 2 | the rest | +120 −60 | behaviour change on the hot path | search p95, error rate | yes, reverts to 2 |

Parallel: <which slices are independent, or "none; a single chain">.
Cost: N PRs and N deploys instead of 1; <what that buys>.
Exceptions: <files split by hunk and why; any glue proposed; or "none, whole files only">.
```

"Review focus" is one line on what could go wrong in that slice. It opens the
slice's PR body and serves as the prompt for a targeted `/code-review`, so make
it concrete ("the lock timeout on the new query"), not generic ("check for
bugs").

## 6. Build

Write `plan.json` in the scratchpad (not in the repo):

```json
{
  "base": "origin/main",
  "head": "origin/feature-x",
  "context": 3,
  "slices": [
    {"id": "schema", "branch": "you/thing-x-column", "after": null,
     "message": "feat(db): add a nullable x column to thing\n\nSearch will read it to ...",
     "paths": ["migrations/versions/abc_add_x.py", "shared/schema/thing.py"]},
    {"id": "reader", "branch": "you/x-reader", "after": "schema",
     "message": "feat(search): add an x reader\n\nReads x for a thing and ...",
     "paths": ["shared/services/x/reader.py", "shared/services/x/test_reader.py"],
     "hunks": ["shared/services/x/__init__.py#0"]}
  ],
  "final": {"branch": "you/search-reads-x", "after": "reader",
            "message": "feat(search): rank by x\n\nSearch now ..."}
}
```

- `paths` takes whole files, as exact copies. A rename must be listed by its new path.
- `hunks` takes ids from `inventory --hunks`, and `context` must match the value used there.
- `after` is one earlier slice id, or `null` for base. Only `final.after` may list several ids; the script then joins them with a merge commit.
- The final slice gets everything left over and carries the original's exact tree. Its branch must be new, and the script refuses the original branch.
- Name branches after what they do, following the prefix convention of the original branch (for example `you/…`). Write commit messages in the repo's commit style (semantic prefix, subject, a body saying why) about this change alone. Take wording from the original PR description and commits where it fits the slice.

Build in this order:

1. Run `python3 $SPLICE build <plan.json> --dry-run`. It builds commits without touching any branch and verifies three things: each slice touches only what it was given, whole files are exact copies, and the final tree equals the original. A forward-reference warning stops the build. Fix the plan by moving the provider earlier or the user later. Pass `--allow-forward-refs` only after reading the code and confirming a match is a false positive, and say which one.
2. Check each non-final slice stands alone, using the cheapest check that would catch a missing import or type. Check out the slice's commit from the dry run with `git worktree add --detach <scratch>/slice-<id> <commit>`. Then:
   - Python: compile and import the changed modules, using an existing virtualenv from the main checkout.
   - TypeScript: run `tsc --noEmit` for the touched package if dependencies are installed.
   - Anything else: run the package's quickest test or typecheck.

   If a proper check needs a full install you don't have, say so plainly and name CI as the gate. Remove the worktrees afterwards.
3. Run `python3 $SPLICE build <plan.json>`. This creates the branches and saves a state file under `.git/splice/` for `restack`. If a branch name already exists, stop and ask. `--force` moves it but keeps a backup ref.

## 7. Hand off

Report each slice: its branch, commit, diff stat and review focus. State the
verification result in one line: "final tree == original tree; whole files
exact; no glue". If you ran standalone checks, say which ones and what they
showed.

Pushing and opening PRs is a separate step. Offer the exact commands and run
them only when the user says yes:

- `git push -u origin <branch>` for each slice.
- `gh pr create --base <parent slice branch, or main> --head <branch> --title "<message subject>" --body <body>` for each slice.
- On the original PR (and only there), a comment saying it is superseded by the new PRs, listed in merge order, and optionally `gh pr ready --undo <n>` so nobody merges it by accident. Close it only once the last slice lands, and only when the user asks.

Write each slice PR in the repo's normal PR format (read a recent merged PR or
the PR template), describing that change on its own terms: what it does, why,
and how it was tested. Take the relevant parts of the original description and
leave the rest. Add three things a good PR carries anyway:

- **Depends on #<parent PR>**, when the slice has a parent. Omit it for slices off main.
- **What to review closely:** the review-focus line from the plan.
- **After deploy, watch:** the deploy-watch signal.

Never mention the original PR, the split, or the slice's position in a
sequence.

Suggest `/code-review <branch>` for the slices whose review focus names a real
risk, and skip it for the mechanical ones.

Never merge. Merging is the user's call, one slice at a time.

## 8. Landing: restack after each squash merge

In a squash-merge repo (check with `gh repo view --json squashMergeAllowed,mergeCommitAllowed,deleteBranchOnMerge`),
a landed slice's commits never reach main. The next slice's PR then shows the
landed changes again until it is restacked. After each merge:

```bash
git fetch origin main
python3 $SPLICE restack --branch <final slice branch> --merged <slice id> --onto origin/main --dry-run
python3 $SPLICE restack --branch <final slice branch> --merged <slice id> --onto origin/main
```

`restack` replays only the slices built on a landed slice, and leaves
independent ones alone. It prints `--force-with-lease` push commands; run them
only after the user confirms. If a replay conflicts because main moved
underneath, it stops and names the slice. Resolve that one by hand, the usual
way.

## 9. Keep the skill sharp

This skill maintains itself. Edit it in place, in its base directory. If
that directory is a checkout of a skills repo, the edit shows up there as a
diff for its owner to commit; if it is a read-only plugin cache, propose the
edit in the final report instead. At the end of every run, before the final
report, ask whether the run taught something a future split would likely need:

- **Script bug or false positive:** fix `scripts/splice.py`. Rerun the plan that exposed it, and one plan the fix must not break. The fix is the record; don't also log it.
- **A seam, constraint or check that generalises:** add one line to `learnings.md` in its format. Examples: a kind of change that deserves its own PR, an ordering a repo's CI or deploy enforces, a standalone check that worked.
- **A learning that has come up three times, or that changes the workflow:** move it into this file where it belongs, and delete it from `learnings.md`.

Skip anything specific to one PR, anything already written here or in the
repo's own docs, and anything unverified. Keep `learnings.md` under about 40
lines by merging and pruning. In the final report, say in one line what you
changed, or say that nothing was worth keeping.

## Safety

- The original branch and PR are never modified.
- Every moved branch gets a `refs/splice-backup/<branch>/<time>` ref, and the state file records every commit.
- Force pushes always use `--force-with-lease` pinned to the SHA the script printed.
- Build and restack commits keep the original author, so authorship stays with the person who wrote the code.

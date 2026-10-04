# splice-pr learnings

Findings from past runs that are likely to apply again. Read before designing
a plan. Each entry is a pattern, not a story about one PR. Format:
`- <pattern>. <why it matters>. (<YYYY-MM-DD>)`

## Seams

- Deletion of the path a switch replaces (old artefacts, the scripts that built them, dead readers) is its own last PR. Merged together, reverting the switch also resurrects deletions; apart, the switch reverts alone. Worth the extra PR when the switch is risky. (2026-09-30)
- A consumer that must understand the new data before it appears (a dashboard or reader that labels rows the switch will start writing) can land as a small independent PR ahead of the switch, so it is ready from the first new row. (2026-09-30)
- Offline tooling (eval harnesses, scripts nothing deploys) is a free parallel slice when it rides along with a product change; on its own it is rarely worth splitting at all. (2026-09-30)
- New telemetry the PR adds (a metric or counter for the thing it fixes) goes in the earliest slice, so the switch's deploy watch has a before-picture to compare against. (2026-09-30)
- Callers of new plumbing often fall into two risk groups (a hot path vs. a broad, shallow change across many routes). Separate them when each has its own deploy signal. (2026-09-30)

## Constraints

- A generated API client (OpenAPI `*.gen.ts` and the like) travels with the backend change that alters the schema; CI's schema check fails otherwise. (2026-09-30)
- If the PR branch is behind main, slices are cut from the merge-base. Before pushing, move them with `restack --onto origin/main --all` (dry run first). (2026-09-30)
- A final slice with several parents can't be opened as a PR against one base without showing its parents' diff. Prefer chaining the parallel slices when they are small; otherwise open the final once its parents land and it has been restacked onto main. (2026-09-30)

## Checks

- Standalone checks that have worked: per-slice worktree, then `tsc --noEmit` and the scoped vitest suite for frontend; compile, import and non-DB pytest for Python. DB-marked tests need Postgres; name them as unrun. (2026-09-30)

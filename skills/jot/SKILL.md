---
name: jot
description: Save a note for the user to read later, as a dated markdown file in their notes folder ($JOT_DIR, default ~/notes; outside every git repo, never committed). By default it summarises the whole conversation. When the user says what to keep (an idea, a decision, a finding, a list, "just the caching bit"), it saves only that. Use this whenever the user asks to jot down, note, save, capture, write up or summarise something "for later", "to my notes" or "so I can collect these", even if they don't say "jot". Not for Claude's own memory (preferences Claude should remember next time), not for temporary working files, and not for docs meant to live in the repo or be shared with a team.
---

# Jot

The user keeps personal notes from working sessions and collects them over time. A note is for them to read cold weeks later, so it has to make sense without the conversation that produced it.

## Where notes go

- **Folder:** `$JOT_DIR` if set, otherwise `~/notes/`. Resolve it with `echo "${JOT_DIR:-$HOME/notes}"`. Create it if it's missing.
  - The notes are personal and must never be committed.
  - Before writing, check the folder isn't inside a git work tree: `git -C <folder> rev-parse --is-inside-work-tree` should fail. If it succeeds, stop and ask the user where to put the note.
- **File name:** `YYYY-MM-DD-<topic-slug>.md`, with today's date and a 2–5 word slug.
- **Index:** `INDEX.md` in the same folder lists every note, newest first, one line each:
  `- [2026-09-28 Cache invalidation plan](2026-09-28-cache-invalidation-plan.md) — hook`
  Update it on every save, so the collection stays browsable.

## Decide the scope

- **The user names what to store** (in the request, or as arguments to `/jot`): store only that. Include just enough background for it to stand on its own.
- **The user doesn't say:** summarise the whole conversation. If a note was already saved earlier in this session, cover only what's new since then.
- **It's ambiguous:** pick the reading that fits the user's words and say which one you chose, rather than asking a round of questions.

## New note or update

- **Check first.** Read `INDEX.md` and list the folder before writing.
- **Same topic as an existing note** (for example, continuing last week's work on the same design): add a dated section (`## Update 2026-10-02`) to that note instead of creating a near-duplicate. Refresh its line in `INDEX.md`.
- **Never delete or rewrite earlier content.** The notes are a record. If something earlier turned out wrong, say so in the new section.
- **New topic:** new file.

## Writing the note

- **Background before mechanics.** Start with what the thing is, why it matters and what problem it solves, then how it works. An idea's steps don't make sense without the context around them.
- **Conclusions, not a narrative.** Record what was learned, decided or proposed, not "then we discussed…".
- **Concise and scannable:**
  - short bullets;
  - tables for numbers and comparisons;
  - code blocks for commands.
- **Keep numbers honest:**
  - date anything that changes ("as of 2026-09-28");
  - keep each number next to its source or dataset;
  - mark anything estimated or unverified.
- **Keep what makes it reusable:** file paths, commands, links, owners, open questions, next steps.
- **Leave out** secrets, credentials and personal data about customers or other people. IDs and aggregates only.
- **Pronouns:** use they/them for anyone whose pronouns haven't been stated.

Use only the sections that have content.

- **Whole-conversation note:** some of Context, Key facts, Decisions, Ideas / backlog, How to run or test, Open questions, Links.
- **Single-item note:** shorter, shaped like this:

```markdown
# Precompute ranking features offline

2026-09-28. Idea, not yet tested.

## Background
- The ranker computes ~40 features per request; three of them are ~80% of p95 latency.
- Those three only change when the underlying record changes, not per request.

## The idea
- Compute them on write, store them alongside the record, and have the ranker read them.

## Why / risks
- …

## Next steps
- …
```

## After saving

Tell the user:
- the path;
- whether it's a new note or an update to an existing one;
- a few words on what it covers.

Don't paste the note back into the chat; it's already in the file.

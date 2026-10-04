# skills

Claude Code skills I use every day, kept here the way dotfiles are: one source
of truth, installable anywhere.

| Skill | What it does | Needs |
| --- | --- | --- |
| [splice-pr](skills/splice-pr/SKILL.md) | Splits one oversized PR into a 2–4 PR stack that each review and deploy safely. Copies the original's files and hunks verbatim, verifies the slices add up to the original byte for byte, and restacks after each squash merge. Says "don't split" when that's the right answer. | `git`, `gh`, `python3` |
| [done](skills/done/SKILL.md) | "Are we done here?" One verdict line plus everything still open: PRs and their live CI state, unfiled follow-ups, things waiting on you, loops still running. Read-only. | `gh` |
| [jot](skills/jot/SKILL.md) | Saves a note to read cold weeks later, as a dated markdown file with an index. Whole conversation by default, or only the bit you name. | — |
| [read-aloud](skills/read-aloud/SKILL.md) | Rewrites a doc, thread, meeting or page as a script for the ear, then plays it with OpenAI or ElevenLabs TTS while later chunks render. | `python3`, an OpenAI or ElevenLabs key; macOS for playback |

## Install

As a Claude Code plugin:

```text
/plugin marketplace add lbennett-stacki/skills
/plugin install lbennett@lbennett-skills
```

Skills are then namespaced, e.g. `/lbennett:splice-pr`.

One skill at a time, with the [`skills`](https://skills.sh) CLI:

```bash
npx skills add lbennett-stacki/skills --skill splice-pr
```

To hack on them, clone and symlink, so edits are live and land as a diff here:

```bash
git clone git@github.com:lbennett-stacki/skills.git ~/workspace/skills
for s in ~/workspace/skills/skills/*/; do ln -sfn "$s" ~/.claude/skills/"$(basename "$s")"; done
```

## Configuration

| Variable | Skill | Default |
| --- | --- | --- |
| `JOT_DIR` | jot | `~/notes` |
| `READ_ALOUD_PROVIDER` | read-aloud | `openai` |
| `READ_ALOUD_ENV_FILES` | read-aloud | — (colon-separated `KEY=value` files to read API keys from) |

Set them in your shell, or in the `env` block of `~/.claude/settings.json`.
See each skill for the rest.

## Contributing to this repo

`scripts/check-leaks.sh` runs before every commit (`scripts/install-hooks.sh`
installs the hook). It greps for private terms listed in a gitignored
`.leak-denylist` and runs `gitleaks` when installed.

## License

MIT

#!/usr/bin/env bash
# Fail if a tracked or staged file names something private. Run before every push;
# the pre-commit hook runs it too (scripts/install-hooks.sh).
set -uo pipefail
root=$(git rev-parse --show-toplevel)
cd "$root"
status=0

# 1. Private terms: one case-insensitive regex per line in the gitignored .leak-denylist.
if [[ -f .leak-denylist ]]; then
  files=$(git ls-files --cached --others --exclude-standard)
  while IFS= read -r term; do
    [[ -z "$term" || "$term" == \#* ]] && continue
    hits=$(printf '%s\n' "$files" | xargs grep -nIiE -- "$term" 2>/dev/null)
    if [[ -n "$hits" ]]; then
      printf 'denylist /%s/:\n%s\n' "$term" "$hits"
      status=1
    fi
  done < .leak-denylist
else
  echo "warn: no .leak-denylist; skipping private-term check" >&2
fi

# 2. Secrets: gitleaks over history and the working tree.
if command -v gitleaks >/dev/null; then
  gitleaks git --no-banner --redact . || status=1
  gitleaks dir --no-banner --redact . || status=1
else
  echo "warn: gitleaks not installed (brew install gitleaks); skipping secret scan" >&2
fi

exit $status

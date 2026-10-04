#!/usr/bin/env bash
# Run the leak check before every commit in this clone.
set -euo pipefail
root=$(git rev-parse --show-toplevel)
printf '#!/usr/bin/env bash\nexec "%s/scripts/check-leaks.sh"\n' "$root" > "$root/.git/hooks/pre-commit"
chmod +x "$root/.git/hooks/pre-commit"
echo "pre-commit hook installed"

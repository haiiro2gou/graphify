#!/usr/bin/env bash
set -euo pipefail

# The ~/.claude volume comes up root-owned on first use.
# Only the volume root: -R would hit the bind mount inside it.
sudo chown "$(id -u):$(id -g)" "$HOME/.claude"

# The feature installs /usr/bin/claude as root; self-update expects ~/.local/bin/claude.
claude install || true

pip install --user uv
# Same as CI (.github/workflows/ci.yml): optional-language tests need the extras.
python -m uv sync --all-extras --frozen

#!/usr/bin/env bash
# Cloud Codespaces setup. Linux cloud supports development/static tests, NOT
# Arrow's native Windows notch, global hooks, UIA, microphone, or screen capture.
set -euo pipefail

echo "[Arrow] Installing cloud-safe Python dependencies..."
python -m pip install --disable-pip-version-check -r .devcontainer/requirements-cloud.txt

echo "[Arrow] Installing OpenCode CLI..."
if ! npm install --global opencode-ai; then
  echo "[Arrow] WARNING: OpenCode installation failed. Retry: npm install -g opencode-ai"
fi

echo "[Arrow] Installing selected Matt Pocock engineering skills for OpenCode..."
if ! npx --yes skills@latest add mattpocock/skills -g -a opencode \
  -s setup-matt-pocock-skills -s diagnosing-bugs -s tdd \
  -s implement -s implement-spec -s codebase-design \
  -s code-review -s research -s pr -y; then
  echo "[Arrow] WARNING: Skills installation failed. See docs/cloud-development.md."
fi

echo "[Arrow] Enabling Ponytail in OpenCode..."
if command -v opencode >/dev/null 2>&1; then
  if ! opencode plugin add @dietrichgebert/ponytail; then
    echo "[Arrow] WARNING: Ponytail installation failed. See docs/cloud-development.md."
  fi
else
  echo "[Arrow] WARNING: OpenCode is not installed, so Ponytail was not installed."
fi

echo "[Arrow] Cloud workspace bootstrap complete."
echo "[Arrow] For checks: bash .devcontainer/check-cloud.sh"
echo "[Arrow] For AI coding: opencode (configure an LLM provider with /connect)"
echo "[Arrow] IMPORTANT: Native Windows behavior needs GitHub Actions and local Windows manual validation."

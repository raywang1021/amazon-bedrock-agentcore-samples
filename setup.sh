#!/usr/bin/env bash
set -e

echo "==> Creating virtual environment..."
python3 -m venv .venv

echo "==> Installing dependencies..."
.venv/bin/pip install -e .

# Fix: prance pulls in chardet which conflicts with charset_normalizer used by requests.
# This causes RequestsDependencyWarning. Remove chardet to resolve.
if .venv/bin/pip show chardet > /dev/null 2>&1; then
    echo "==> Fixing chardet/charset_normalizer conflict..."
    .venv/bin/pip uninstall chardet -y
fi

echo ""
echo "Done! Run 'source .venv/bin/activate' to get started."
echo "Then 'agentcore configure' to set up your AWS environment."

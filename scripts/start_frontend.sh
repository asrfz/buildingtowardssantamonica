#!/usr/bin/env bash
# HomePulse — start Vite dev server from repo root (macOS / Linux).
# Usage:  chmod +x scripts/start_frontend.sh && ./scripts/start_frontend.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/frontend"
if [[ ! -d node_modules ]]; then
  echo "Installing npm dependencies..."
  npm install
fi
npm run dev

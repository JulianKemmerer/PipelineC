#!/usr/bin/env bash
# Render the PypelineC tool flow diagram (flow.dot) to PNG and SVG.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
dot -Tpng flow.dot > flow.png
dot -Tsvg flow.dot > flow.svg
echo "Wrote $(pwd)/flow.png and $(pwd)/flow.svg"

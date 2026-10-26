#!/usr/bin/env bash

# Convenience wrapper for rendering an EvoluPark scenario with the project's venv.
set -euo pipefail
exec python engine/render.py "$@"
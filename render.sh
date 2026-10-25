#!/usr/bin/env bash
set -euo pipefail

# Render video with voice-over narration
# Disable Manim caching to prevent audio from disappearing
manim -pqh --disable_caching engine/render.py ConsultationScene

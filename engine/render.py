# SPDX-FileCopyrightText: 2026 Gwenolé Quellec
# SPDX-License-Identifier: MIT

"""Command-line entry point for rendering an EvoluPark YAML scenario.

Select a named scenario and preview quality, then launch Manim with the
corresponding configuration. Rendering logic lives in ``scene.py``.

Examples
--------
python engine/render.py inclusion --low
python engine/render.py inclusion --medium
python engine/render.py inclusion --high
"""

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
SCENE_FILE = Path(__file__).with_name("scene.py")
QUALITY_FLAGS = {
    "low": "-ql",
    "medium": "-qm",
    "high": "-qh",
}


def parse_arguments(argv=None):
    """Parse the mandatory scenario name and optional rendering quality."""
    parser = argparse.ArgumentParser(
        description="Render an EvoluPark scenario as a narrated MP4 video.",
    )
    parser.add_argument(
        "scenario",
        help="Scenario name in scenarios/ (e.g., inclusion or inclusion.yaml).",
    )
    quality = parser.add_mutually_exclusive_group()
    quality.add_argument("--low", dest="quality", action="store_const", const="low",
                         help="Fast, low-resolution preview.")
    quality.add_argument("--medium", dest="quality", action="store_const", const="medium",
                         help="Medium-resolution preview (default).")
    quality.add_argument("--high", dest="quality", action="store_const", const="high",
                         help="High-resolution final render.")
    parser.set_defaults(quality="medium")
    return parser.parse_args(argv)


def resolve_scenario(name):
    """Validate a scenario name and return its absolute YAML file path."""
    stem = name[:-5] if name.endswith(".yaml") else name
    if not re.fullmatch(r"[A-Za-z0-9_-]+", stem):
        raise ValueError(f"Invalid scenario name: {name!r}")
    path = ROOT / "scenarios" / f"{stem}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"Scenario not found: {path}")
    return stem, path.resolve()


def build_command(name, quality):
    """Build the Manim command while keeping output naming scenario-based."""
    return [
        sys.executable, "-m", "manim",
        "-p", QUALITY_FLAGS[quality],
        "--disable_caching",  # Work around missing voice-over audio with cached frames.
        "--format=mp4",
        "-o", name,
        str(SCENE_FILE), "EvoluParkScene",
    ]


def main(argv=None):
    """Launch Manim using the selected YAML file and propagate its exit code."""
    args = parse_arguments(argv)
    try:
        stem, scenario_path = resolve_scenario(args.scenario)
    except (ValueError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    env = os.environ.copy()
    env["EVOLUPARK_SCENARIO"] = str(scenario_path)
    command = build_command(stem, args.quality)

    print(f"Scenario: {scenario_path}", flush=True)
    print(f"Quality:  {args.quality}", flush=True)
    print(f"Output:   {stem}.mp4", flush=True)
    return subprocess.call(command, cwd=ROOT, env=env)


if __name__ == "__main__":
    raise SystemExit(main())

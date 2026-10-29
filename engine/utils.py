# SPDX-FileCopyrightText: 2026 Gwenolé Quellec
# SPDX-License-Identifier: MIT

"""Shared SVG geometry and frame-cycling helpers for EvoluPark/Manim.

This module does not depend on the current scenario. It is reusable from
``engine.scene`` (characters) and ``engine.room`` (room decorations).
All asset paths are relative to the project root; normalized anchors use a
bottom-left origin. Continuous SVG animation is driven by Manim updaters,
not by blocking ``Scene.play`` calls.
"""

from pathlib import Path

import numpy as np
from manim import SVGMobject, UP


ROOT = Path(__file__).resolve().parent.parent


def load_svg(relative_path, height=None, native_facing="right", facing="right", *, width=None):
    """Load an SVG, scale it and optionally flip it horizontally.

    Args:
        relative_path: SVG path relative to the repository root.
        height: Target Manim height; positional for backward compatibility.
        native_facing: Artwork's original orientation (``left`` or ``right``).
        facing: Requested orientation.
        width: Alternative target width, mutually exclusive with ``height``.

    Returns:
        A ``(mobject, flipped)`` pair.
    """
    if (height is None) == (width is None):
        raise ValueError("Specify exactly one of 'height' and 'width'.")
    if native_facing not in {"left", "right"} or facing not in {"left", "right"}:
        raise ValueError(f"Invalid facing: {facing!r} (native: {native_facing!r})")

    path = (ROOT / relative_path).resolve()
    if not path.is_relative_to(ROOT.resolve()):
        raise ValueError(f"Asset path is outside the project: {relative_path}")
    if not path.is_file():
        raise FileNotFoundError(f"SVG asset not found: {path}")

    obj = SVGMobject(str(path))
    if height is not None:
        obj.scale_to_fit_height(float(height))
    else:
        obj.scale_to_fit_width(float(width))
    flipped = native_facing != facing
    if flipped:
        obj.flip(axis=UP)
    return obj, flipped


def place_bottom(obj, x, bottom_y):
    """Position a mobject using horizontal center and its bottom edge."""
    obj.set_x(float(x))
    obj.shift((float(bottom_y) - obj.get_bottom()[1]) * UP)


def place_object(obj, spec):
    """Place an asset using ``x`` and either ``bottom_y`` or center ``y``."""
    if "bottom_y" in spec and "y" in spec:
        raise ValueError("Use 'bottom_y' or 'y', not both")
    x = float(spec.get("x", 0))
    if "bottom_y" in spec:
        place_bottom(obj, x, spec["bottom_y"])
    else:
        obj.move_to([x, float(spec.get("y", 0)), 0])


def anchor_point(obj, anchor, flipped=False):
    """Get a normalized bounding-box point, optionally mirrored on X."""
    x, y = float(anchor["x"]), float(anchor["y"])
    if flipped:
        x = 1 - x
    if not (0 <= x <= 1 and 0 <= y <= 1):
        raise ValueError(f"Anchor outside [0, 1]: {anchor}")
    return np.array([
        obj.get_left()[0] + x * obj.width,
        obj.get_bottom()[1] + y * obj.height,
        0.0,
    ])


def make_looping_svg(frames, *, period, initial_phase=0.0, z_index=0):
    """Create a Manim mobject that cycles preloaded SVG poses continuously.

    Each input frame must already be scaled and positioned. The entire list is
    cached in memory, so no SVG is parsed by the per-frame updater. ``period``
    is the full animation-cycle duration in seconds, not the delay per SVG.

    The returned object advances automatically whenever Manim renders a frame
    (during ``Scene.play`` and ``Scene.wait``), including while audio is played.
    """
    if not frames:
        raise ValueError("A looping animation needs at least one SVG frame")
    period = float(period)
    if period <= 0:
        raise ValueError("Animation period must be > 0")

    start_time = float(initial_phase) % period
    start_index = int(len(frames) * start_time / period)
    shown = frames[start_index].copy()
    shown.set_z_index(z_index)
    if len(frames) == 1:
        return shown

    state = {"time": start_time, "index": start_index}

    def advance(mobject, dt):
        """Switch SVG only when the discrete animation frame changes."""
        state["time"] = (state["time"] + max(0.0, float(dt))) % period
        next_index = int(len(frames) * state["time"] / period)
        if next_index != state["index"]:
            mobject.become(frames[next_index])
            mobject.set_z_index(z_index)
            state["index"] = next_index

    shown.add_updater(advance)
    return shown

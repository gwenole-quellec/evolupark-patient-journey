# SPDX-FileCopyrightText: 2026 Gwenolé Quellec
# SPDX-License-Identifier: MIT

"""Shared SVG loading, positioning, and animation utilities for EvoluPark.

This module provides reusable helpers for scene and room objects, including
character poses, normalized anchors, and SVG frame cycling.

Asset paths are relative to the project root. Normalized anchors use a
bottom-left origin. Looping animations use non-blocking Manim updaters.
"""

from math import cos, pi, sin
from pathlib import Path

import numpy as np
import yaml
from manim import RIGHT, SVGMobject, UP, VGroup, VMobject


# ==============================================================================
# Constants
# ==============================================================================

ROOT = Path(__file__).resolve().parent.parent
COMMON_CONFIG = ROOT / "config" / "common.yaml"
with COMMON_CONFIG.open(encoding="utf-8") as f:
    common_cfg = yaml.safe_load(f) or {}


# ==============================================================================
# Asset loading
# ==============================================================================

def build_svg_object(spec):
    """Build a static or looping SVG object from a YAML specification.

    Supports:
        - Static SVG files or animated frame sequences
        - Width or height scaling
        - Horizontal position and center/bottom vertical alignment
        - Horizontal flipping
        - Opacity and z-index
        - Optional periodic motion

    Args:
        spec: YAML object definition.

    Returns:
        A (mobject, flipped) pair.
    """
    name = spec.get("id", "<unnamed>")
    animated = "animation" in spec
    has_file = "file" in spec

    if animated == has_file:
        raise ValueError(
            f"{name!r}: specify exactly one of file or animation"
        )

    width = spec.get("width")
    height = spec.get("height")

    if (width is None) == (height is None):
        raise ValueError(
            f"{name!r}: specify exactly one of width or height"
        )

    animation = spec["animation"] if animated else None
    paths = animation["frames"] if animated else [spec["file"]]

    if not paths:
        raise ValueError(f"{name!r}: no SVG frames provided")

    native_facing = spec.get("native_facing", "right")
    facing = spec.get("facing", native_facing)
    z_index = int(spec["z_index"])
    opacity = float(spec.get("opacity", 1.0))

    frames = []
    flipped = False

    for path in paths:
        frame, flipped = load_svg(
            path,
            height=height,
            width=width,
            native_facing=native_facing,
            facing=facing,
        )

        place_object(frame, spec)
        frame.set_opacity(opacity)
        frame.set_z_index(z_index)
        frames.append(frame)

    if animated:
        obj = make_looping_svg(
            frames,
            period=animation.get("period", 2.0),
            initial_phase=animation.get("phase", 0.0),
            z_index=z_index,
        )
    else:
        obj = frames[0]

    add_motion(obj, spec.get("motion"))

    return obj, flipped


def load_character(name, pose, facing):
    """Load one pose of a named character at its configured height and facing.

    ``walking`` is a virtual pose: it uses the first ``walking_frames`` entry,
    so no ``poses.walking`` entry is required in the shared YAML.

    Returns:
        A ``(SVGMobject, flipped)`` pair.
    """
    spec = common_cfg["characters"][name]
    if pose == "walking" and spec.get("walking_frames"):
        path = spec["walking_frames"][0]
    else:
        path = spec["poses"][pose]

    native = spec.get("native_facing", "right")
    if isinstance(native, dict):
        native = native.get(pose, "right")

    return load_svg(
        path,
        spec.get("heights", {}).get(pose, 3.5),
        native_facing=native,
        facing=facing,
    )


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


# ==============================================================================
# Asset positioning
# ==============================================================================

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


def place_bottom(obj, x, y):
    """Position a mobject using horizontal center and its bottom edge."""
    obj.set_x(float(x))
    obj.shift((float(y) - obj.get_bottom()[1]) * UP)


def place_object(obj, spec):
    """Place an asset using ``x`` and ``y``."""
    x = float(spec.get("x", 0))
    if "y" in spec:
        place_bottom(obj, x, spec["y"])
        #obj.move_to([x, float(spec.get("y", 0)), 0])


# ==============================================================================
# Motion utilities
# ==============================================================================

def add_motion(obj, motion):
    """Attach a periodic position updater to a Manim mobject.

    Supports 'ping_pong' (movement followed by a pause) and 'sine'
    (continuous oscillation). Motion amplitude, period, and phase
    are specified in the motion configuration.

    Returns:
        The original mobject with its updater attached.
    """
    if not motion:
        return obj

    kind = motion.get("type", "ping_pong")
    if kind not in {"ping_pong", "sine"}:
        raise ValueError(f"Unknown motion type: {kind}")

    dx = float(motion.get("dx", 0.0))
    dy = float(motion.get("dy", 0.0))
    period = float(motion.get("period", 4.0))
    active_fraction = float(motion.get("active_fraction", 0.5))
    phase = float(motion.get("phase", 0.0))

    if period <= 0:
        raise ValueError("Motion period must be positive")
    if not 0 < active_fraction <= 1:
        raise ValueError("active_fraction must be in (0, 1]")

    origin = obj.get_center().copy()
    displacement = dx * RIGHT + dy * UP
    elapsed = 0.0

    def update(mob, dt):
        nonlocal elapsed
        elapsed = (elapsed + max(0.0, float(dt))) % period
        t = (elapsed / period + phase) % 1.0

        if kind == "ping_pong":
            # Move out and back, then remain stationary.
            if t < active_fraction:
                alpha = sin(pi * t / active_fraction) ** 2
            else:
                alpha = 0.0
        else:
            # Continuous smooth back-and-forth movement.
            alpha = (1 - cos(2 * pi * t)) / 2

        mob.move_to(origin + alpha * displacement)

    obj.add_updater(update)
    return obj


def make_looping_svg(frames, *, period, initial_phase=0.0, z_index=0):
    """Cycle through preloaded SVG frames by toggling their visibility.

    All frames remain in a single group, preserving a constant bounding
    box and avoiding structural changes during animation.

    Args:
        frames: Preloaded, positioned SVG mobjects.
        period: Duration of one complete cycle, in seconds.
        initial_phase: Initial offset within the cycle, in seconds.
        z_index: Rendering layer of the animated object.

    Returns:
        A VGroup with a non-blocking frame-cycling updater.
    """
    if not frames:
        raise ValueError("A looping animation needs at least one SVG frame")

    period = float(period)
    if period <= 0:
        raise ValueError("Animation period must be > 0")

    group = VGroup(*frames)
    group.set_z_index(z_index)

    # Preserve the original fill and stroke opacities of every shape.
    styles = [
        [
            (
                part,
                part.get_fill_opacity(),
                part.get_stroke_opacity(),
            )
            for part in frame.get_family()
            if isinstance(part, VMobject)
        ]
        for frame in frames
    ]

    def set_visible(index, visible):
        """Toggle a frame without changing its geometry or colors."""
        for part, fill, stroke in styles[index]:
            part.set_fill(
                opacity=fill if visible else 0,
                family=False,
            )
            part.set_stroke(
                opacity=stroke if visible else 0,
                family=False,
            )

    start_time = float(initial_phase) % period
    start_index = int(len(frames) * start_time / period)

    for i in range(len(frames)):
        if i != start_index:
            set_visible(i, False)

    state = {
        "time": start_time,
        "index": start_index,
    }

    def advance(mobject, dt):
        """Display the frame corresponding to the current cycle time."""
        state["time"] = (
            state["time"] + max(0.0, float(dt))
        ) % period

        next_index = int(
            len(frames) * state["time"] / period
        )

        if next_index != state["index"]:
            set_visible(state["index"], False)
            set_visible(next_index, True)
            state["index"] = next_index

    if len(frames) > 1:
        group.add_updater(advance)

    return group


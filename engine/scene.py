# SPDX-FileCopyrightText: 2026 Gwenolé Quellec
# SPDX-License-Identifier: MIT

"""Generic Manim scene engine driven by an EvoluPark YAML scenario.

The launcher in ``render.py`` sets ``EVOLUPARK_SCENARIO`` before invoking Manim.
This module renders characters, furniture, backgrounds, and text. Narration
synthesis and caching are implemented separately in ``engine.voice``.
"""

import os
from pathlib import Path

import numpy as np
import yaml
from manim import (
    DOWN,
    Line,
    Rectangle,
    RIGHT,
    Scene,
    SVGMobject,
    Text,
    UL,
    UP,
    UR,
    Write,
    config,
    linear,
)
from engine.voice import generate_voice


ROOT = Path(__file__).resolve().parent.parent
SCENARIO_ENV = os.environ.get("EVOLUPARK_SCENARIO")
if not SCENARIO_ENV:
    raise RuntimeError(
        "EVOLUPARK_SCENARIO is not set. Use 'python engine/render.py <scenario>'."
    )
SCENARIO = Path(SCENARIO_ENV)
if not SCENARIO.is_file():
    raise FileNotFoundError(f"Scenario not found: {SCENARIO}")
with SCENARIO.open(encoding="utf-8") as stream:
    cfg = yaml.safe_load(stream)
if not isinstance(cfg, dict):
    raise ValueError(f"Scenario must contain a YAML mapping: {SCENARIO}")


def load_svg(relative_path, height, native_facing="right", facing="right"):
    """Load a colored SVG and optionally mirror it to face the other way."""
    path = ROOT / relative_path
    if not path.is_file():
        raise FileNotFoundError(path)
    if facing not in {"right", "left"} or native_facing not in {"right", "left"}:
        raise ValueError(f"Invalid facing: {facing!r} (native: {native_facing!r})")

    obj = SVGMobject(str(path))
    obj.scale_to_fit_height(float(height))
    flipped = facing != native_facing
    if flipped:
        obj.flip(axis=UP)
    return obj, flipped


def load_character(name, pose, facing):
    """Load the configured SVG pose and requested orientation of a character."""
    spec = cfg["characters"][name]
    native = spec.get("native_facing", "right")
    if isinstance(native, dict):
        native = native.get(pose, "right")
    return load_svg(
        spec["poses"][pose],
        spec.get("heights", {}).get(pose, 3.5),
        native_facing=native,
        facing=facing,
    )


def place_bottom(obj, x, bottom_y):
    """Move an object to horizontal center ``x`` and bottom position ``bottom_y``."""
    obj.set_x(float(x))
    obj.shift((float(bottom_y) - obj.get_bottom()[1]) * UP)


def anchor_point(obj, anchor, flipped=False):
    """Return a normalized bounding-box anchor, measured from the bottom-left."""
    x = float(anchor["x"])
    y = float(anchor["y"])
    if flipped:
        x = 1.0 - x
    if not (0 <= x <= 1 and 0 <= y <= 1):
        raise ValueError(f"Anchor outside [0, 1]: {anchor}")
    return np.array([
        obj.get_left()[0] + x * obj.width,
        obj.get_bottom()[1] + y * obj.height,
        0.0,
    ])


class EvoluParkScene(Scene):
    """Render a YAML-defined EvoluPark scene with characters and narration."""

    def construct(self):
        """Build the static scene, then execute all narrated YAML sequences."""
        style = cfg["style"]
        scene_cfg = cfg.get("scene", {})
        self.people = {}
        self.furniture_on_stage = {}

        frame_width = config.frame_width
        frame_height = config.frame_height
        self.camera.background_color = style.get("background", style["wall_color"])

        # Wall, floor and boundary line.
        wall = Rectangle(
            width=frame_width,
            height=frame_height,
            fill_color=style["wall_color"],
            fill_opacity=1,
            stroke_width=0,
        )
        wall.set_z_index(-30)
        self.add(wall)

        floor_y = float(scene_cfg.get("floor_y", -2.6))
        frame_bottom = -frame_height / 2
        floor_height = floor_y - frame_bottom
        if not 0 < floor_height < frame_height:
            raise ValueError(f"floor_y is outside the scene: {floor_y}")

        floor = Rectangle(
            width=frame_width,
            height=floor_height,
            fill_color=style["floor_color"],
            fill_opacity=1,
            stroke_width=0,
        )
        floor.move_to([0, frame_bottom + floor_height / 2, 0])
        floor.set_z_index(-29)
        self.add(floor)

        horizon = Line(
            [-frame_width / 2, floor_y, 0],
            [frame_width / 2, floor_y, 0],
            color=style["brand_grey_light"],
            stroke_width=1.5,
        )
        horizon.set_z_index(-28)
        self.add(horizon)

        # Optional background illustration.
        decor_cfg = scene_cfg.get("background_decor")
        if decor_cfg:
            decor_path = ROOT / decor_cfg["file"]
            if not decor_path.is_file():
                raise FileNotFoundError(decor_path)
            decor = SVGMobject(str(decor_path))
            decor.scale_to_fit_width(float(decor_cfg.get("width", 5.5)))
            decor.move_to([
                float(decor_cfg.get("x", -4.2)),
                float(decor_cfg.get("y", 0.2)),
                0,
            ])
            decor.set_opacity(float(decor_cfg.get("opacity", 0.13)))
            decor.set_z_index(-20)
            self.add(decor)

        # Title in the upper-left corner.
        title = Text(
            cfg["title"],
            font=style.get("font", "Liberation Sans"),
            weight="BOLD",
            font_size=32,
            color=style["brand_teal"],
        )
        if title.width > 8.7:
            title.scale_to_fit_width(8.7)
        title.to_corner(UL, buff=0.4)
        title.set_z_index(20)
        self.add(title)

        # EvoluPark logo in the upper-right corner.
        logo_cfg = cfg.get("logo", {})
        logo_path = ROOT / logo_cfg.get("file", "assets/logo/evolupark.svg")
        if not logo_path.is_file():
            raise FileNotFoundError(logo_path)
        logo = SVGMobject(str(logo_path))
        logo.scale_to_fit_width(float(logo_cfg.get("width", 1.65)))
        logo.to_corner(UR, buff=0.35)
        logo.set_z_index(20)
        self.add(logo)

        self.add_furniture()
        for sequence in cfg["sequences"]:
            self.run_sequence(sequence)
        self.wait(0.5)

    def add_furniture(self):
        """Create named furniture instances with their individual poses and sizes."""
        for instance in cfg.get("scene", {}).get("furniture", []):
            instance_id = instance["id"]
            if instance_id in self.furniture_on_stage:
                raise ValueError(f"Duplicate furniture instance: {instance_id}")

            furniture_type = instance["type"]
            spec = cfg["furniture"][furniture_type]
            facing = instance.get("facing", spec.get("native_facing", "right"))
            obj, flipped = load_svg(
                spec["file"],
                instance.get("height", spec.get("height", 2.0)),
                native_facing=spec.get("native_facing", "right"),
                facing=facing,
            )
            place_bottom(obj, instance["x"], instance["bottom_y"])
            z = 3 if furniture_type == "coffee_table" else 0
            obj.set_z_index(z)
            self.add(obj)
            self.furniture_on_stage[instance_id] = {
                "mobject": obj,
                "type": furniture_type,
                "flipped": flipped,
            }

    def enter(self, action, run_time):
        """Animate a new character entering the frame from the specified side."""
        name = action["character"]
        if name in self.people:
            raise ValueError(f"Character already on stage: {name}")
        pose = action["pose"]
        facing = action.get("facing", "right")
        obj, flipped = load_character(name, pose, facing)
        obj.set_z_index(2)

        destination = action["to"]
        x = float(destination["x"])
        bottom_y = float(destination.get("bottom_y", -2.6))
        side = action["from"]
        if side not in {"left", "right"}:
            raise ValueError(f"Invalid entry side: {side}")

        sign = -1 if side == "left" else 1
        start_x = sign * (config.frame_width / 2 + obj.width / 2 + 0.2)
        place_bottom(obj, start_x, bottom_y)
        self.add(obj)
        self.play(
            obj.animate.shift((x - start_x) * RIGHT),
            run_time=run_time,
            rate_func=linear,
        )
        self.people[name] = {
            "mobject": obj,
            "pose": pose,
            "facing": facing,
            "flipped": flipped,
        }

    def change_pose(self, action):
        """Instantly replace the current SVG with another pose or orientation."""
        name = action["character"]
        previous = self.people[name]
        pose = action["pose"]
        facing = action.get("facing", previous["facing"])
        if pose == previous["pose"] and facing == previous["facing"]:
            return

        old = previous["mobject"]
        new, flipped = load_character(name, pose, facing)
        place_bottom(new, old.get_center()[0], old.get_bottom()[1])
        new.set_z_index(2)
        self.remove(old)
        self.add(new)
        self.people[name] = {
            "mobject": new,
            "pose": pose,
            "facing": facing,
            "flipped": flipped,
        }

    def sit_on(self, action):
        """Align the character's sitting anchor with a named chair's seat anchor."""
        name = action["character"]
        previous = self.people[name]
        pose = action.get("pose", "sitting")
        facing = action.get("facing", previous["facing"])
        chair_id = action["chair"]
        chair_state = self.furniture_on_stage[chair_id]
        furniture_spec = cfg["furniture"][chair_state["type"]]
        character_spec = cfg["characters"][name]

        new, flipped = load_character(name, pose, facing)
        character_anchor = character_spec["anchors"][pose]["seat"]
        chair_anchor = furniture_spec["anchors"]["seat"]
        target = anchor_point(
            chair_state["mobject"], chair_anchor, chair_state["flipped"]
        )
        current = anchor_point(new, character_anchor, flipped)
        new.shift(target - current)
        new.set_z_index(2)

        self.remove(previous["mobject"])
        self.add(new)
        self.people[name] = {
            "mobject": new,
            "pose": pose,
            "facing": facing,
            "flipped": flipped,
        }

    def show_text(self, action, run_time):
        """Draw a short explanatory caption over the bottom of the scene."""
        message = Text(
            action["text"],
            font=cfg["style"]["font"],
            weight="SEMIBOLD",
            font_size=28,
            color=cfg["style"]["brand_grey"],
        )
        message.scale_to_fit_width(11)
        message.to_edge(DOWN, buff=0.25)
        message.set_z_index(10)
        self.play(Write(message), run_time=run_time)

    def execute_action(self, action, run_time=0):
        """Dispatch a YAML action to its corresponding animation operation."""
        kind = action["action"]
        if kind == "enter":
            self.enter(action, run_time)
        elif kind in {"stop", "change_pose"}:
            self.change_pose(action)
        elif kind == "sit_on":
            self.sit_on(action)
        elif kind == "show_text":
            self.show_text(action, run_time)
        else:
            raise ValueError(f"Unknown action: {kind}")

    def run_sequence(self, sequence):
        """Synchronize each action with its narration without fading SVG layers."""
        narration = sequence.get("narration", "").strip()
        if narration:
            audio_path, duration = generate_voice(narration, cfg["voice"])
            self.add_sound(str(audio_path))
        else:
            duration = float(sequence.get("duration", 2.0))

        actions = sequence.get("actions", [])
        animated = {"enter", "show_text"}
        animated_count = sum(a["action"] in animated for a in actions)
        motion_time = duration * 0.75 if animated_count else 0.0
        step = motion_time / animated_count if animated_count else 0.0

        for action in actions:
            self.execute_action(action, step if action["action"] in animated else 0)

        remaining = duration - motion_time
        if remaining > 0:
            self.wait(remaining)

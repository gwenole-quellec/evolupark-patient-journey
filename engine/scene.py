# SPDX-FileCopyrightText: 2026 Gwenolé Quellec
# SPDX-License-Identifier: MIT

"""Render EvoluPark narrated scenarios inside reusable YAML-defined rooms.

The launcher (``engine/render.py``) selects a scenario through the
``EVOLUPARK_SCENARIO`` environment variable. Shared resources are read from
``config/common.yaml``; the scenario supplies its title, a ``scene.room`` path
and ordered ``scene.sequences``.

``engine.room`` handles walls, floors, furniture and independently looping
background animations. ``engine.utils`` provides shared SVG loading and
positioning functions. This module manages characters, walking cycles, seating,
explanatory text and narration; speech synthesis is in ``engine.voice``.
"""

import os
from pathlib import Path

import yaml
from manim import (
    DOWN,
    RIGHT,
    Scene,
    SVGMobject,
    Text,
    UL,
    UP,
    UpdateFromAlphaFunc,
    UR,
    Write,
    config,
    linear,
)

from engine.room import Room
from engine.utils import (
    ROOT,
    add_motion,
    anchor_point,
    load_svg,
    make_looping_svg,
    place_bottom,
    place_object,
)
from engine.voice import generate_voice


# ==============================================================================
# Scenario configuration
# ==============================================================================

SCENARIO_ENV = os.environ.get("EVOLUPARK_SCENARIO")
if not SCENARIO_ENV:
    raise RuntimeError(
        "EVOLUPARK_SCENARIO is not set. Use 'python engine/render.py <scenario>'."
    )

SCENARIO = Path(SCENARIO_ENV)
if not SCENARIO.is_file():
    raise FileNotFoundError(f"Scenario not found: {SCENARIO}")

COMMON_CONFIG = ROOT / "config" / "common.yaml"
with COMMON_CONFIG.open(encoding="utf-8") as f:
    common_cfg = yaml.safe_load(f) or {}
with SCENARIO.open(encoding="utf-8") as f:
    scenario_cfg = yaml.safe_load(f) or {}

# Shared definitions and scenario data have distinct top-level keys.
cfg = {**common_cfg, **scenario_cfg}


def load_character(name, pose, facing):
    """Load one pose of a named character at its configured height and facing.

    ``walking`` is a virtual pose: it uses the first ``walking_frames`` entry,
    so no ``poses.walking`` entry is required in the shared YAML.

    Returns:
        A ``(SVGMobject, flipped)`` pair.
    """
    spec = cfg["characters"][name]
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


class EvoluParkScene(Scene):
    """Orchestrate narrated character actions in a reusable Manim room.

    Room objects are registered in ``room_objects`` by their YAML identifiers.
    Named furniture with a shared type is also available under
    ``furniture_on_stage``; this supports chair-based positioning with
    ``sit_on``. Room SVG animations remain active during all scene actions.
    """

    def construct(self):
        """Build the selected room, add branding, then run scenario sequences."""
        scene_cfg = cfg.get("scene", {})
        room_path = scene_cfg.get("room")
        if not room_path:
            raise ValueError(
                f"Scenario {SCENARIO} must define 'scene.room' "
                "(e.g. 'rooms/examination.yaml')."
            )

        self.people = {}
        self.illustrations = {}
        self.room = Room.from_yaml(room_path, shared=cfg)
        self.room_objects = self.room.build(self)
        self.furniture_on_stage = {
            name: state
            for name, state in self.room_objects.items()
            if "seat" in state.get("anchors", {})
        }

        style = cfg["style"]

        # Keep title and logo above all room objects and characters.
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

        logo_cfg = cfg.get("logo", {})
        logo_path = ROOT / logo_cfg.get("file", "assets/logo/evolupark.svg")
        if not logo_path.is_file():
            raise FileNotFoundError(logo_path)
        logo = SVGMobject(str(logo_path))
        logo.scale_to_fit_width(float(logo_cfg.get("width", 1.65)))
        logo.to_corner(UR, buff=0.35)
        logo.set_z_index(20)
        self.add(logo)

        for sequence in scene_cfg["sequences"]:
            self.run_sequence(sequence)
        self.wait(0.5)

    def animate_walk(
        self,
        obj,
        name,
        facing,
        start_x,
        end_x,
        bottom_y,
        run_time,
    ):
        """Walk a character horizontally using distance-synchronized SVG frames.

        SVG frames are preloaded. Their order is not reversed when the figure
        faces left; ``load_svg`` mirrors the illustrations instead. If fewer
        than two walking frames exist, the character simply slides.

        Args:
            obj: On-stage character mobject to update.
            name: Identifier in ``common.yaml:characters``.
            facing: Requested left/right orientation.
            start_x: Horizontal starting position.
            end_x: Horizontal destination.
            bottom_y: Height of the character's feet in scene coordinates.
            run_time: Time allotted to the movement, in seconds.
        """
        spec = cfg["characters"][name]
        paths = spec.get("walking_frames", [])

        if len(paths) < 2:
            self.play(
                obj.animate.shift((end_x - start_x) * RIGHT),
                run_time=run_time,
                rate_func=linear,
            )
            return

        native = spec.get("native_facing", "right")
        if isinstance(native, dict):
            native = native.get("walking", "right")
        height = spec.get("heights", {}).get("walking", 3.5)

        frames = [
            load_svg(
                path,
                height,
                native_facing=native,
                facing=facing,
            )[0]
            for path in paths
        ]

        cycle_length = float(spec.get("walk_cycle_length", 2.0))
        if cycle_length <= 0:
            raise ValueError("walk_cycle_length must be positive")

        current_frame = -1
        frame_count = len(frames)
        distance = abs(end_x - start_x)

        def update(mob, alpha):
            """Advance the gait frame as distance accumulates."""
            nonlocal current_frame

            x = start_x + alpha * (end_x - start_x)
            traveled = alpha * distance
            phase = (traveled / cycle_length) % 1.0
            frame_index = min(int(phase * frame_count), frame_count - 1)

            if frame_index != current_frame:
                mob.become(frames[frame_index])
                mob.set_z_index(2)
                current_frame = frame_index
            place_bottom(mob, x, bottom_y)

        self.play(
            UpdateFromAlphaFunc(
                obj,
                update,
                run_time=run_time,
                rate_func=linear,
            )
        )

    def enter(self, action, run_time):
        """Introduce a character from a frame edge to its target position."""
        name = action["character"]
        if name in self.people:
            raise ValueError(f"Character already on stage: {name}")

        pose = action["pose"]
        facing = action.get("facing", "right")
        obj, flipped = load_character(name, pose, facing)
        obj.set_z_index(2)

        destination = action["to"]
        x = float(destination["x"])
        bottom_y = float(destination.get("bottom_y", self.room.floor_y))
        side = action["from"]
        if side not in {"left", "right"}:
            raise ValueError(f"Invalid entry side: {side}")

        sign = -1 if side == "left" else 1
        start_x = sign * (config.frame_width / 2 + obj.width / 2 + 0.2)
        place_bottom(obj, start_x, bottom_y)
        self.add(obj)

        if pose == "walking":
            self.animate_walk(
                obj=obj,
                name=name,
                facing=facing,
                start_x=start_x,
                end_x=x,
                bottom_y=bottom_y,
                run_time=run_time,
            )
        else:
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
        """Instantly replace a character's pose without shifting its feet."""
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
        """Align the character's seat anchor with a named room chair's anchor."""
        name = action["character"]
        previous = self.people[name]
        pose = action.get("pose", "sitting")
        facing = action.get("facing", previous["facing"])
        chair_id = action["chair"]

        if chair_id not in self.room_objects:
            raise ValueError(f"Unknown room object for sit_on: {chair_id!r}")
        chair_state = self.room_objects[chair_id]
        chair_anchor = chair_state.get("anchors", {}).get("seat")
        if chair_anchor is None:
            raise ValueError(
                f"Room object {chair_id!r} has no 'anchors.seat'. "
                "Define this anchor in the room YAML."
            )

        character_spec = cfg["characters"][name]
        character_anchor = character_spec["anchors"][pose]["seat"]
        new, flipped = load_character(name, pose, facing)

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

    def show_illustration(self, action):
        """Show or replace a static or looping scenario illustration."""
        name = action["id"]
        animated = "animation" in action

        if animated == ("file" in action):
            raise ValueError(
                f"{name!r}: specify either file or animation"
            )

        width = action.get("width")
        height = action.get("height")
        if (width is None) == (height is None):
            raise ValueError(
                f"{name!r}: specify exactly one of width or height"
            )

        paths = (
            action["animation"]["frames"]
            if animated else [action["file"]]
        )

        z_index = int(action.get("z_index", 8))
        frames = []

        native_facing = action.get("native_facing", "right")
        facing = action.get("facing", native_facing)

        for path in paths:
            frame, _ = load_svg(
                path,
                height=height,
                width=width,
                native_facing=native_facing,
                facing=facing,
            )
            place_object(frame, action)
            frame.set_z_index(z_index)
            frames.append(frame)

        if animated:
            animation = action["animation"]
            obj = make_looping_svg(
                frames,
                period=animation.get("period", 2.0),
                initial_phase=animation.get("phase", 0.0),
                z_index=z_index,
            )
        else:
            obj = frames[0]

        previous = self.illustrations.pop(name, None)
        if previous is not None:
            self.remove(previous["mobject"])

        add_motion(obj, action.get("motion"))

        self.add(obj)
        self.illustrations[name] = {"mobject": obj}

    def hide_illustration(self, action):
        """Remove a named illustration immediately."""
        name = action["id"]
        previous = self.illustrations.pop(name, None)
        if previous is not None:
            self.remove(previous["mobject"])

    def show_text(self, action, run_time):
        """Write a short explanatory caption near the bottom of the frame."""
        message = Text(
            action["text"],
            font=cfg["style"].get("font", "Liberation Sans"),
            weight="SEMIBOLD",
            font_size=28,
            color=cfg["style"]["brand_grey"],
        )
        if message.width > 11:
            message.scale_to_fit_width(11)
        message.to_edge(DOWN, buff=0.25)
        message.set_z_index(10)
        self.play(Write(message), run_time=run_time)

    def execute_action(self, action, run_time=0):
        """Dispatch a scenario action to its character or caption operation."""
        kind = action["action"]
        if kind == "show_illustration":
            self.show_illustration(action)
        elif kind == "hide_illustration":
            self.hide_illustration(action)
        elif kind == "enter":
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
        """Play narrated actions, leaving remaining narration time for a pause.

        Room animation updaters keep running during movements and pauses. Speech
        audio is generated/cached by ``engine.voice`` and added once per sequence.
        """
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

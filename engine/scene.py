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
from math import hypot
from pathlib import Path

import yaml
from manim import (
    DOWN,
    LEFT,
    Scene,
    SVGMobject,
    Text,
    UL,
    UpdateFromAlphaFunc,
    UR,
    config,
    linear,
)

from engine.room import Room
from engine.utils import (
    ROOT,
    anchor_point,
    build_svg_object,
    load_character,
    load_svg,
    place_bottom,
)
from engine.voice import generate_voice


# ==============================================================================
# Constants
# ==============================================================================

SCENARIO_ENV = os.environ.get("EVOLUPARK_SCENARIO")
if not SCENARIO_ENV:
    raise RuntimeError(
        "EVOLUPARK_SCENARIO is not set. Use 'python engine/render.py <scenario>'."
    )

SCENARIO = Path(SCENARIO_ENV)
if not SCENARIO.is_file():
    raise FileNotFoundError(f"Scenario not found: {SCENARIO}")

TITLE_Z_INDEX = 1000
TEXT_Z_INDEX = 999

COMMON_CONFIG = ROOT / "config" / "common.yaml"
with COMMON_CONFIG.open(encoding="utf-8") as f:
    common_cfg = yaml.safe_load(f) or {}
with SCENARIO.open(encoding="utf-8") as f:
    scenario_cfg = yaml.safe_load(f) or {}

# Shared definitions and scenario data have distinct top-level keys.
cfg = {**common_cfg, **scenario_cfg}


# ==============================================================================
# Scene engine class
# ==============================================================================

class EvoluParkScene(Scene):
    """Orchestrate narrated character actions in a reusable Manim room.

    Room objects are registered in ``room_objects`` by their YAML identifiers.
    Room SVG animations remain active during all scene actions.
    """

    def animate_walk(
        self,
        obj,
        name,
        waypoints,
        run_time,
        facing=None,
        defer=False,
    ):
        """Animate walking along a polyline at a specified duration.

        Walking frames are synchronized with the distance traveled,
        independently of animation duration.

        When defer=True, prepare the animation without playing it.

        Returns:
            The final facing direction, or an (animation, facing) pair when
            deferred. The animation is None for a zero-length path or a
            nonpositive duration.
        """
        points = [(float(x), float(y)) for x, y in waypoints]

        if len(points) < 2:
            raise ValueError("Walking requires at least two points")

        spec = cfg["characters"][name]
        paths = spec.get("walking_frames", [])
        cycle_length = float(spec.get("walk_cycle_length", 2.0))

        if cycle_length <= 0:
            raise ValueError("walk_cycle_length must be positive")

        # Build nonzero-length segments.
        segments = []
        total_length = 0.0
        previous_facing = facing or self.people[name]["facing"]

        for (x0, y0), (x1, y1) in zip(points[:-1], points[1:]):
            dx = x1 - x0
            dy = y1 - y0
            length = hypot(dx, dy)

            if length < 1e-8:
                continue

            if facing is not None:
                direction = facing
            elif dx > 1e-8:
                direction = "right"
            elif dx < -1e-8:
                direction = "left"
            else:
                direction = previous_facing

            previous_facing = direction
            total_length += length

            segments.append({
                "x0": x0,
                "y0": y0,
                "dx": dx,
                "dy": dy,
                "length": length,
                "end_distance": total_length,
                "facing": direction,
            })

        if not segments:
            place_bottom(obj, *points[-1])
            if defer:
                return None, previous_facing
            return previous_facing

        # Preload walking frames for each orientation.
        native = spec.get("native_facing", "right")
        if isinstance(native, dict):
            native = native.get("walking", "right")

        height = spec.get("heights", {}).get("walking", 3.5)
        frames_by_facing = {}

        for direction in {s["facing"] for s in segments}:
            if len(paths) >= 2:
                frames_by_facing[direction] = [
                    load_svg(
                        path,
                        height,
                        native_facing=native,
                        facing=direction,
                    )[0]
                    for path in paths
                ]
            else:
                frames_by_facing[direction] = [
                    load_character(name, "standing", direction)[0]
                ]

        z_index = obj.z_index
        current_key = None

        def update(mob, alpha):
            nonlocal current_key

            distance = alpha * total_length

            # Find current segment.
            index = 0
            while (
                index < len(segments) - 1
                and distance > segments[index]["end_distance"]
            ):
                index += 1

            segment = segments[index]

            start_distance = (
                segments[index - 1]["end_distance"]
                if index > 0 else 0.0
            )

            progress = (
                (distance - start_distance) / segment["length"]
            )
            progress = max(0.0, min(1.0, progress))

            x = segment["x0"] + progress * segment["dx"]
            y = segment["y0"] + progress * segment["dy"]

            # Synchronize gait with distance traveled.
            frames = frames_by_facing[segment["facing"]]
            phase = (distance / cycle_length) % 1.0
            frame_index = min(
                int(phase * len(frames)),
                len(frames) - 1,
            )

            key = (segment["facing"], frame_index)

            if key != current_key:
                mob.become(frames[frame_index])
                mob.set_z_index(z_index)
                current_key = key

            place_bottom(mob, x, y)

        if run_time <= 0:
            update(obj, 1.0)
            if defer:
                return None, segments[-1]["facing"]
            return segments[-1]["facing"]

        animation = UpdateFromAlphaFunc(
            obj,
            update,
            run_time=run_time,
            rate_func=linear,
        )

        if defer:
            # Prepared but not yet played.
            return animation, segments[-1]["facing"]

        self.play(animation)
        return segments[-1]["facing"]

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
        new.set_z_index(old.z_index)
        self.remove(old)
        self.add(new)
        self.people[name] = {
            "mobject": new,
            "pose": pose,
            "facing": facing,
            "flipped": flipped,
        }

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
        title.set_z_index(TITLE_Z_INDEX)
        self.add(title)
        self.title = title
        self.current_text = None

        logo_cfg = cfg.get("logo", {})
        logo_path = ROOT / logo_cfg.get("file", "assets/logo/evolupark.svg")
        if not logo_path.is_file():
            raise FileNotFoundError(logo_path)
        logo = SVGMobject(str(logo_path))
        logo.scale_to_fit_width(float(logo_cfg.get("width", 1.65)))
        logo.to_corner(UR, buff=0.35)
        logo.set_z_index(TITLE_Z_INDEX)
        self.add(logo)

        for sequence in scene_cfg["sequences"]:
            self.run_sequence(sequence)
        self.wait(0.5)

    def execute_action(self, action):
        """Dispatch a YAML action and return its duration when applicable."""
        kind = action["action"]
        if kind == "show_illustration":
            self.show_illustration(action)
        elif kind == "hide_illustration":
            self.hide_illustration(action)
        elif kind == "change_pose":
            self.change_pose(action)
        elif kind == "sit_on":
            self.sit_on(action)
        elif kind == "show_text":
            self.show_text(action)
        elif kind == "place_character":
            self.place_character(action)
        elif kind == "stand_up":
            self.stand_up(action)
        elif kind == "walk_to":
            return self.walk_to(action)
        elif kind == "parallel":
            return self.parallel(action)
        elif kind == "set_z_index":
            self.set_character_z_index(action)
        else:
            raise ValueError(f"Unknown action: {kind}")

    def hide_illustration(self, action):
        """Remove a named illustration immediately."""
        name = action["id"]
        previous = self.illustrations.pop(name, None)
        if previous is not None:
            self.remove(previous["mobject"])

    def parallel(self, action):
        """Execute multiple walking actions simultaneously.

        Each character uses its own walking speed. Only walk_to actions are
        supported, and each character may appear at most once.

        Returns:
            The duration of the longest movement, in seconds.
        """
        actions = action.get("actions", [])

        if not actions:
            raise ValueError("parallel requires at least one action")

        animations = []
        finishers = []
        characters = set()
        total_duration = 0.0

        for sub_action in actions:
            if sub_action["action"] != "walk_to":
                raise ValueError(
                    f"Unsupported parallel action: {sub_action['action']}"
                )

            name = sub_action["character"]

            if name in characters:
                raise ValueError(
                    f"Duplicate character in parallel: {name}"
                )

            characters.add(name)

            animation, finalize, duration = self.walk_to(
                sub_action,
                defer=True,
            )

            if animation is not None:
                animations.append(animation)

            finishers.append(finalize)
            total_duration = max(total_duration, duration)

        if animations:
            self.play(*animations)

        for finalize in finishers:
            finalize()

        return total_duration

    def place_character(self, action):
        """Place a character immediately, optionally seated on a chair."""
        name = action["character"]

        if name in self.people:
            raise ValueError(f"Character already on stage: {name}")

        pose = action.get("pose", "standing")
        facing = action.get("facing", "right")

        obj, flipped = load_character(name, pose, facing)
        obj.set_z_index(int(
            action.get("z_index", cfg["characters"][name]["z_index"])
        ))

        if "chair" not in action:
            position = self.room.resolve_position(action)
            x = float(position["x"])
            y = float(position.get(
                "y",
                self.room.definition.get("character_ground_y", self.room.floor_y),
            ))
            place_bottom(obj, x, y)

        self.add(obj)

        self.people[name] = {
            "mobject": obj,
            "pose": pose,
            "facing": facing,
            "flipped": flipped,
        }

        if "chair" in action:
            self.sit_on({
                "character": name,
                "chair": action["chair"],
                "pose": pose,
                "facing": facing,
            })

    def run_sequence(self, sequence):
        """Execute a sequence with narration and independent action timing.

        Narration starts at the beginning of the sequence. Actions run
        sequentially, except those grouped in a parallel action.

        The sequence continues until both the narration and all actions have
        finished, respecting any configured minimum duration.
        """
        narration = sequence.get("narration", "").strip()

        if narration:
            audio_path, audio_duration = generate_voice(
                narration, cfg["voice"]
            )
            self.add_sound(str(audio_path))
        else:
            audio_duration = 0.0

        elapsed = 0.0

        for action in sequence.get("actions", []):
            elapsed += self.execute_action(action) or 0.0

        # Optional minimum sequence duration.
        minimum_duration = float(sequence.get("duration", 0.0))
        target_duration = max(audio_duration, minimum_duration)

        # Wait if the narration is longer than the visual actions.
        remaining = target_duration - elapsed

        if remaining > 0:
            self.wait(remaining)

    def set_character_z_index(self, action):
        """Change a character's rendering depth without replacing its pose."""
        name = action["character"]

        if name not in self.people:
            raise ValueError(f"Character not on stage: {name}")

        self.people[name]["mobject"].set_z_index(
            int(action["z_index"])
        )

    def show_illustration(self, action):
        """Show or replace a named scenario illustration."""
        name = action["id"]

        obj, _ = build_svg_object(self.room.resolve_position(action))

        previous = self.illustrations.pop(name, None)

        if previous is not None:
            self.remove(previous["mobject"])

        self.add(obj)

        self.illustrations[name] = {
            "mobject": obj,
        }

    def show_text(self, action):
        """Display a caption below the title, replacing the previous one."""

        # Remove previous caption.
        if self.current_text is not None:
            self.remove(self.current_text)

        message = Text(
            action["text"],
            font=cfg["style"].get("font", "Liberation Sans"),
            weight="SEMIBOLD",
            font_size=26,
            color=cfg["style"]["brand_grey"],
        )

        if message.width > 8.7:
            message.scale_to_fit_width(8.7)

        # Position below the scene title, left-aligned.
        message.next_to(self.title, DOWN, buff=0.18)
        message.align_to(self.title, LEFT)
        message.set_z_index(TEXT_Z_INDEX)

        # Display immediately, without animation.
        self.add(message)
        self.current_text = message

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
        new.set_z_index(previous["mobject"].z_index)

        self.remove(previous["mobject"])
        self.add(new)
        self.people[name] = {
            "mobject": new,
            "pose": pose,
            "facing": facing,
            "flipped": flipped,
        }

    def stand_up(self, action):
        """Instantly change a character to a standing pose and reposition it."""
        name = action["character"]

        if name not in self.people:
            raise ValueError(f"Unknown character: {name}")

        previous = self.people[name]
        facing = action.get("facing", previous["facing"])

        self.change_pose({
            "character": name,
            "pose": action.get("pose", "standing"),
            "facing": facing,
        })

        position = self.room.resolve_position(action.get("to", action))
        obj = self.people[name]["mobject"]

        place_bottom(
            obj,
            float(position["x"]),
            float(position.get(
                "y",
                self.room.definition.get("character_ground_y", self.room.floor_y),
            )),
        )

    def walk_to(self, action, defer=False):
        """Move a character along a path at its configured walking speed.

        Accepts a destination or multiple waypoints, with optional entry from
        outside the frame. Walking speed and final pose can be overridden by
        the action.

        When deferred, prepare the animation without playing it.

        Returns:
            The movement duration, or an (animation, finalize, duration) tuple
            when deferred.
        """
        name = action["character"]

        if "path" in action:
            targets = action["path"]
        elif "to" in action:
            targets = [action["to"]]
        elif "location" in action:
            targets = [action]
        else:
            targets = []

        if not isinstance(targets, list) or not targets:
            raise ValueError(
                f"{name}: walk_to requires a destination or path"
            )

        targets = [
            self.room.resolve_position(target)
            for target in targets
        ]

        for target in targets:
            if not isinstance(target, dict) or "x" not in target:
                raise ValueError(
                    f"{name}: every waypoint requires an x coordinate"
                )

        # Create character outside the frame if necessary.
        if name not in self.people:
            side = action.get("from")
            if side not in {"left", "right"}:
                raise ValueError(
                    f"{name} is not on stage: specify from: left/right"
                )

            initial_facing = action.get(
                "facing",
                "right" if side == "left" else "left",
            )

            obj, flipped = load_character(
                name, "walking", initial_facing
            )

            sign = -1 if side == "left" else 1
            start_x = sign * (
                config.frame_width / 2 + obj.width / 2 + 0.2
            )
            start_y = float(
                targets[0].get("y", self.room.floor_y)
            )

            place_bottom(obj, start_x, start_y)
            obj.set_z_index(int(
                action.get("z_index", cfg["characters"][name]["z_index"])
            ))
            self.add(obj)

            self.people[name] = {
                "mobject": obj,
                "pose": "walking",
                "facing": initial_facing,
                "flipped": flipped,
            }

        previous = self.people[name]
        obj = previous["mobject"]

        start_x = float(obj.get_center()[0])
        start_y = float(obj.get_bottom()[1])

        # Current position is the first waypoint.
        waypoints = [(start_x, start_y)]

        for target in targets:
            last_y = waypoints[-1][1]
            waypoints.append((
                float(target["x"]),
                float(target.get("y", last_y)),
            ))

        # Distance along the complete trajectory, including waypoints.
        distance = sum(
            hypot(x1 - x0, y1 - y0)
            for (x0, y0), (x1, y1)
            in zip(waypoints[:-1], waypoints[1:])
        )

        speed = float(action.get(
            "speed",
            cfg["characters"][name].get("walk_speed", 1.5),
        ))

        if speed <= 0:
            raise ValueError(
                f"{name}: walk_speed must be positive"
            )

        run_time = distance / speed if distance > 1e-8 else 0.0

        # Determine initial walking direction.
        facing = action.get("facing")

        if facing is None:
            initial_facing = previous["facing"]

            for (x0, _), (x1, _) in zip(
                waypoints[:-1], waypoints[1:]
            ):
                if abs(x1 - x0) > 1e-8:
                    initial_facing = (
                        "right" if x1 > x0 else "left"
                    )
                    break
        else:
            initial_facing = facing

        self.change_pose({
            "character": name,
            "pose": "walking",
            "facing": initial_facing,
        })

        obj = self.people[name]["mobject"]
        place_bottom(obj, start_x, start_y)

        result = self.animate_walk(
            obj=obj,
            name=name,
            waypoints=waypoints,
            run_time=run_time,
            facing=facing,
            defer=defer,
        )

        if defer:
            animation, final_facing = result
        else:
            final_facing = result

        def finalize():
            """Replace walking frames with the final static pose."""
            self.change_pose({
                "character": name,
                "pose": action.get("end_pose", "standing"),
                "facing": final_facing,
            })

        if defer:
            return animation, finalize, run_time

        finalize()
        return run_time

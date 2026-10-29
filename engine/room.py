# SPDX-FileCopyrightText: 2026 Gwenolé Quellec
# SPDX-License-Identifier: MIT

"""Load and render reusable room definitions for EvoluPark Manim scenes.

A room YAML describes wall/floor geometry and a list of scenery objects.
Objects may be static (``file``) or looped (``animation.frames``). Instances
may refer to a shared ``common.yaml`` furniture ``type``; local properties
such as file, size, position, orientation and seat anchors take precedence.

Room animations run through non-blocking updaters, independently of narrated
scenario actions. ``Room.build(scene)`` returns an index of named objects,
including metadata needed to attach a seated character to a room chair.
"""

from pathlib import Path

import yaml
from manim import Line, Rectangle, config

from engine.utils import ROOT, load_svg, make_looping_svg, place_object


class Room:
    """A reusable background and object layout shared by several scenarios."""

    def __init__(self, definition, *, shared, source=None):
        """Store a parsed room definition and the merged global configuration."""
        if not isinstance(definition, dict):
            raise ValueError(f"Room YAML must be a mapping: {source}")
        self.definition = definition
        self.shared = shared
        self.source = source
        self.objects = {}

    @classmethod
    def from_yaml(cls, relative_path, *, shared):
        """Read a room YAML path relative to the repository root."""
        path = (ROOT / relative_path).resolve()
        if not path.is_relative_to(ROOT.resolve()):
            raise ValueError(f"Room path is outside the project: {relative_path}")
        if not path.is_file():
            raise FileNotFoundError(f"Room YAML not found: {path}")
        with path.open(encoding="utf-8") as stream:
            data = yaml.safe_load(stream) or {}
        return cls(data, shared=shared, source=path)

    def build(self, scene):
        """Draw the room and return its named, addressable scenery objects.

        Call once at the beginning of ``Scene.construct()``; all background
        elements remain present for the duration of the scenario.
        """
        self._draw_room_surfaces(scene)
        for entry in self.definition.get("objects", []):
            self._add_object(scene, entry)
        return self.objects

    def _draw_room_surfaces(self, scene):
        """Render wall, floor and dividing line behind scenery and characters."""
        style = self.shared["style"]
        wall_color = self.definition.get("wall_color", style["wall_color"])
        floor_color = self.definition.get("floor_color", style["floor_color"])
        floor_y = float(self.definition.get("floor_y", -2.6))

        frame_w = config.frame_width
        frame_h = config.frame_height
        frame_bottom = -frame_h / 2
        floor_h = floor_y - frame_bottom
        if not 0 < floor_h < frame_h:
            raise ValueError(f"Invalid floor_y={floor_y} in {self.source}")

        scene.camera.background_color = wall_color
        wall = Rectangle(
            width=frame_w, height=frame_h,
            fill_color=wall_color, fill_opacity=1, stroke_width=0,
        )
        wall.set_z_index(-30)
        scene.add(wall)

        floor = Rectangle(
            width=frame_w, height=floor_h,
            fill_color=floor_color, fill_opacity=1, stroke_width=0,
        )
        floor.move_to([0, frame_bottom + floor_h / 2, 0])
        floor.set_z_index(-29)
        scene.add(floor)

        horizon = Line(
            [-frame_w / 2, floor_y, 0],
            [frame_w / 2, floor_y, 0],
            color=self.definition.get("horizon_color", style["brand_grey_light"]),
            stroke_width=1.5,
        )
        horizon.set_z_index(-28)
        scene.add(horizon)
        self.floor_y = floor_y

    def _add_object(self, scene, entry):
        """Instantiate a static asset or an animated sequence of SVG assets."""
        if not isinstance(entry, dict) or "id" not in entry:
            raise ValueError(f"Room object needs an 'id': {entry}")
        name = entry["id"]
        if name in self.objects:
            raise ValueError(f"Duplicate object id in room: {name}")

        furniture_type = entry.get("type")
        defaults = self.shared.get("furniture", {}).get(furniture_type, {})
        spec = {**defaults, **entry}
        spec["anchors"] = {**defaults.get("anchors", {}), **entry.get("anchors", {})}

        # Explicit room properties override type defaults. In particular, a
        # width override replaces the inherited furniture height, and a local
        # animation replaces the furniture type's default static SVG file.
        animated = "animation" in entry
        if animated and "file" in entry:
            raise ValueError(f"'{name}' must not define both 'file' and 'animation'")
        if not animated and not spec.get("file"):
            raise ValueError(f"'{name}' requires a 'file' or 'animation'")
        if "width" in entry and "height" not in entry:
            spec.pop("height", None)
        if "height" in entry and "width" not in entry:
            spec.pop("width", None)
        if ("height" in spec) == ("width" in spec):
            raise ValueError(f"'{name}' needs exactly one of 'height' or 'width'")

        native = spec.get("native_facing", "right")
        facing = spec.get("facing", native)
        z_index = int(spec.get("z_index", 0))
        paths = (
            spec["animation"]["frames"] if animated else [spec["file"]]
        )
        if not paths:
            raise ValueError(f"'{name}' animation has no SVG frames")

        frames = []
        flipped = False
        for path in paths:
            obj, flipped = load_svg(
                path,
                height=spec.get("height"),
                width=spec.get("width"),
                native_facing=native,
                facing=facing,
            )
            place_object(obj, spec)
            obj.set_opacity(float(spec.get("opacity", 1.0)))
            obj.set_z_index(z_index)
            frames.append(obj)

        if animated:
            animation = spec["animation"]
            obj = make_looping_svg(
                frames,
                period=animation.get("period", 2.0),
                initial_phase=animation.get("phase", 0),
                z_index=z_index,
            )
        else:
            obj = frames[0]

        scene.add(obj)
        self.objects[name] = {
            "mobject": obj,
            "type": furniture_type,
            "flipped": flipped,
            "anchors": spec["anchors"],
        }

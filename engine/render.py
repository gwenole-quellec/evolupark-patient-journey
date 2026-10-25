"""
Rendering script.

Author: Gwenolé Quellec
Year: 2026
"""

import asyncio
import hashlib
from pathlib import Path

import edge_tts
import yaml
from mutagen.mp3 import MP3
from manim import *


ROOT = Path(__file__).resolve().parent.parent
AUDIO_CACHE = ROOT / ".cache" / "voice"
AUDIO_CACHE.mkdir(parents=True, exist_ok=True)

with open(
    ROOT / "scenarios" / "consultation.yaml",
    encoding="utf-8",
) as f:
    cfg = yaml.safe_load(f)


def load_character(name, pose, facing):
    """Load and orient a character pose."""

    spec = cfg["characters"][name]
    path = ROOT / spec["poses"][pose]

    if not path.is_file():
        raise FileNotFoundError(path)

    character = SVGMobject(str(path))

    height = spec.get("heights", {}).get(
        pose, 3.5
    )
    character.set_height(height)

    native_facing = spec.get("native_facing", "right")

    if isinstance(native_facing, dict):
        native_facing = native_facing.get(
            pose, "right"
        )

    if facing != native_facing:
        character.flip(axis=UP)

    return character


def generate_voice(text):
    """Generate and cache French speech as MP3."""

    text = " ".join(text.split())
    voice = cfg["voice"]["name"]
    rate = cfg["voice"].get("rate", "+0%")

    key = f"{voice}|{rate}|{text}"
    digest = hashlib.sha256(
        key.encode("utf-8")
    ).hexdigest()[:16]

    path = AUDIO_CACHE / f"{digest}.mp3"

    if not path.exists():
        print(f"Generating speech: {text[:60]}...")

        async def synthesize():
            tts = edge_tts.Communicate(
                text=text,
                voice=voice,
                rate=rate,
            )
            await tts.save(str(path))

        try:
            asyncio.run(synthesize())
        except Exception:
            path.unlink(missing_ok=True)
            raise

    duration = MP3(str(path)).info.length
    return path, duration


class ConsultationScene(Scene):

    def place_character(self, character, x, bottom_y):
        """Position a character using its bottom edge."""

        character.move_to([x, 0, 0])
        character.shift(
            (bottom_y - character.get_bottom()[1]) * UP
        )

    def change_pose(self, action):
        """Replace a character's pose without fading."""

        name = action["character"]
        state = self.characters_on_stage[name]

        pose = action["pose"]
        facing = action.get("facing", state["facing"])

        # No replacement needed if nothing changed
        if (
            pose == state["pose"]
            and facing == state["facing"]
        ):
            return

        old = state["mobject"]
        x = old.get_center()[0]
        bottom_y = state["bottom_y"]

        new = load_character(name, pose, facing)
        self.place_character(new, x, bottom_y)

        self.remove(old)
        self.add(new)

        self.characters_on_stage[name] = {
            "mobject": new,
            "pose": pose,
            "facing": facing,
            "bottom_y": bottom_y,
        }

    def execute_action(self, action, run_time=0):
        """Interpret one action from the YAML scenario."""

        kind = action["action"]

        if kind == "enter":
            name = action["character"]
            pose = action["pose"]
            facing = action.get("facing", "right")

            character = load_character(
                name, pose, facing
            )

            destination = action["to"]
            target_x = float(destination["x"])
            bottom_y = float(
                destination.get("bottom_y", -2.6)
            )

            # Start completely outside the frame
            margin = (
                config.frame_width / 2
                + character.width / 2
                + 0.5
            )

            side = action["from"]

            if side == "left":
                start_x = -margin
            elif side == "right":
                start_x = margin
            else:
                raise ValueError(
                    f"Unknown entry side: {side}"
                )

            self.place_character(
                character, start_x, bottom_y
            )

            self.add(character)

            self.play(
                character.animate.shift(
                    (target_x - start_x) * RIGHT
                ),
                run_time=run_time,
            )

            self.characters_on_stage[name] = {
                "mobject": character,
                "pose": pose,
                "facing": facing,
                "bottom_y": bottom_y,
            }

        elif kind in ("stop", "change_pose"):
            self.change_pose(action)

        elif kind == "show_text":
            message = Text(
                action["text"],
                font_size=28,
                color=cfg["style"]["text_color"],
            )
            message.scale_to_fit_width(11)
            message.to_edge(DOWN, buff=0.25)

            self.play(
                Write(message),
                run_time=run_time,
            )

        else:
            raise ValueError(
                f"Unknown action: {kind}"
            )

    def run_sequence(self, sequence):
        """Synchronize YAML actions with narration."""

        narration = sequence.get("narration", "").strip()

        if narration:
            audio_path, duration = generate_voice(
                narration
            )
            self.add_sound(str(audio_path))
        else:
            duration = float(
                sequence.get("duration", 2.0)
            )

        actions = sequence.get("actions", [])

        # These actions need animation time.
        animated_kinds = {"enter", "show_text"}

        animated_count = sum(
            action["action"] in animated_kinds
            for action in actions
        )

        motion_time = (
            duration * 0.75 if animated_count else 0
        )

        step = (
            motion_time / animated_count
            if animated_count else 0
        )

        for action in actions:
            if action["action"] in animated_kinds:
                self.execute_action(
                    action, run_time=step
                )
            else:
                # Instantaneous pose changes
                self.execute_action(action)

        # Let narration finish
        remaining = duration - motion_time

        if remaining > 0:
            self.wait(remaining)

    def construct(self):

        self.camera.background_color = (
            cfg["style"]["background"]
        )

        self.characters_on_stage = {}

        color = cfg["style"]["text_color"]

        # Title
        title = Text(
            cfg["title"],
            font_size=34,
            color=color,
        ).to_edge(UP, buff=0.5)

        self.add(title)

        # Temporary chair
        chair_color = "#A0ADB7"

        chair = VGroup(
            Rectangle(
                width=1.4,
                height=0.12,
                fill_color=chair_color,
                fill_opacity=1,
                stroke_width=0,
            ).move_to([-2, -1.2, 0]),

            Line(
                [-2.55, -1.25, 0],
                [-2.55, -2.6, 0],
                color=chair_color,
                stroke_width=5,
            ),

            Line(
                [-1.45, -1.25, 0],
                [-1.45, -2.6, 0],
                color=chair_color,
                stroke_width=5,
            ),
        )

        self.add(chair)

        # Entire animation defined by YAML
        for sequence in cfg["sequences"]:
            self.run_sequence(sequence)

        self.wait(0.5)

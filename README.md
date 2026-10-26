<!-- SPDX-FileCopyrightText: 2026 Gwenolé Quellec -->
<!-- SPDX-License-Identifier: MIT -->

# EvoluPark – Patient Journey

Python-based, YAML-driven animations explaining the **EvoluPark clinical study** and the patient journey.

<p align="center">
  <img src="assets/logo/evolupark.png" width="220">
</p>

The project uses [Manim Community](https://www.manim.community/) for animation, SVG illustrations for characters and environments, and French text-to-speech narration generated with [Edge TTS](https://github.com/rany2/edge-tts) or [Piper TTS](https://github.com/OHF-voice/piper1-gpl).

Each YAML scenario is rendered as a narrated MP4 video using a shared animation engine. The goal is to create and update educational sequences without writing scene-specific Python code.

## Getting started

### Requirements

- Python 3
- FFmpeg and the system libraries required by Manim
- Python dependencies listed in `requirements.txt`

On Ubuntu, install the system dependencies if they are not already present:

```bash
sudo apt update
sudo apt install -y ffmpeg pkg-config build-essential \
    python3-dev python3-venv libcairo2-dev libpango1.0-dev
```

Create and activate the virtual environment, then install the Python dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### Render an existing scenario

To render scenario `scenarios/inclusion.yaml`, for instance, pass the scenario name (*without* its `.yaml` extension) to `engine/render.py`:

```bash
python engine/render.py inclusion
```

This will create video **`inclusion.mp4`**. The default render quality is **medium**. It can be changed as follows:

```bash
python engine/render.py inclusion --low       # Fast preview (480p, 15 fps)
python engine/render.py inclusion --medium    # Standard preview (720p, 30 fps)
python engine/render.py inclusion --high      # Final render (1080p, 60 fps)
python engine/render.py --help
```

Manim stores rendered files under `media/videos/` in a quality-dependent subdirectory, and the launcher opens the video after rendering.

The first synthesis of a narration requires an internet connection, either to download a TTS model (with `Piper TTS`), or to run one online (with `Edge TTS`).

> Note: the render command disables Manim's animation cache to avoid an audio-loss issue observed when re-rendering narrated scenes. Generated voice-over MP3 files are cached separately in `.cache/voice/` and reused when the narration text, voice and speech rate have not changed.

## Creating a scenario

EvoluPark separates shared configuration from scenario-specific content:

- **`config/common.yaml`** defines the visual style, logo, voice synthesis settings (local Piper or remote Edge TTS), characters, poses, walking animation frames, furniture types, and spatial anchors.
- **`scenarios/*.yaml`** defines the title and content of each animation, including its background, furniture instances, and ordered sequences of narrated actions.

All scenarios use the same `EvoluParkScene` animation engine.

### Creating a new scenario

1. Create a YAML file such as `scenarios/walking.yaml`, following the structure of `scenarios/inclusion.yaml`.
2. Define its `title` and `scene` properties. The `scene` section contains the background settings, furniture instances, and `sequences`, each with optional narration and a list of actions.
3. Reference existing characters, furniture types, and SVG assets using their definitions in `config/common.yaml`. Asset paths are relative to the project root.
4. Render the scenario using:

   ```bash
   python engine/render.py walking --low
   ```

   Use `--medium` (the default) for regular previews or `--high` for final rendering. The output video is named after the scenario (e.g., `walking.mp4`).

### Characters and animations

The engine currently supports character entry (`enter`), pose changes (`change_pose`, `stop`), sitting on named chairs (`sit_on`), and displaying text (`show_text`).

Character definitions are shared across scenarios in `config/common.yaml`. To add a new static pose, register its SVG under the character's `poses` property.

Walking animations use an ordered list of SVG files under `walking_frames`, with `walk_cycle_length` controlling the distance traveled per gait cycle. When a character enters with `pose: walking`, the engine automatically cycles through these frames during movement.

The `native_facing` property specifies the original orientation of the artwork; the engine mirrors SVGs when necessary. Fractional spatial anchors are used to align seated characters with furniture.

New activities, such as gait assessments, handwriting tests, and home questionnaires, can reuse the same engine as additional action types are implemented.

## Credits and third-party artwork

This project incorporates and adapts illustrations from the following collections:

- **[Humaaans](https://www.humaaans.com/)** — created by **Pablo Stanley**. Used for characters, poses and some background elements. **License:** [CC0 1.0 Universal](https://creativecommons.org/publicdomain/zero/1.0/).
- **[FreeSVG](https://freesvg.org/)** — community-contributed SVG illustrations, including furniture and other scene objects. **License:** [CC0 1.0 Universal](https://creativecommons.org/publicdomain/zero/1.0/). See [FreeSVG's terms](https://freesvg.org/pages/terms-and-conditions).

Thanks to these creators and contributors for making their artwork available for reuse and adaptation. Attribution is not required under CC0, but is provided here in recognition of their work.

## License

The **original EvoluPark Python code, scripts and YAML scenarios** in this repository are released under the **MIT License** (see [`LICENSE`](LICENSE)), subject to the applicable ownership rights.

**Third-party SVG illustrations are not relicensed under MIT.** Humaaans and FreeSVG illustrations retain their CC0 status, including when recolored, rearranged or otherwise adapted for this project. Other assets, including logos or material from additional providers, may have separate rights and should be documented individually before redistribution.

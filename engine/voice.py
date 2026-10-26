# SPDX-FileCopyrightText: 2026 Gwenolé Quellec
# SPDX-License-Identifier: MIT

"""Generate and cache voice-over audio for EvoluPark animations.

The YAML configuration selects an offline Piper voice (``local: true``) or
Microsoft Edge TTS (``local: false``). Piper produces WAV files, while Edge
TTS produces MP3 files. Both are cached in ``.cache/voice/``.

To use an offline Piper voice, install Piper and the French Siwis voice (once,
from the project root)::

    mkdir -p assets/voices
    python -m piper.download_voices --data-dir assets/voices fr_FR-siwis-medium

The download creates ``fr_FR-siwis-medium.onnx`` and the accompanying
``fr_FR-siwis-medium.onnx.json`` under ``assets/voices/``. After the download,
Piper synthesis is fully offline. To use a different local voice, download its
model to the same directory and change ``voice.model`` in the YAML.

Example YAML for local synthesis::

    voice:
      local: true
      model: fr_FR-siwis-medium
      speaker: 0
      length_scale: 1.05

Example YAML for remote synthesis (requires ``edge-tts`` and Internet)::

    voice:
      local: false
      name: fr-FR-VivienneMultilingualNeural
      rate: "-5%"

Only this module owns the synthesis dependencies, audio cache, and duration
measurement. The Manim scene uses ``generate_voice(text, voice_config)``.
"""

import asyncio
import hashlib
from pathlib import Path
import subprocess
import sys
import wave

import edge_tts
from mutagen.mp3 import MP3


ROOT = Path(__file__).resolve().parent.parent
AUDIO_CACHE = ROOT / ".cache" / "voice"


def generate_voice(text: str, voice_config: dict) -> tuple[Path, float]:
    """Generate or reuse narrated audio with Piper or Edge TTS.

    Args:
        text: Narration text, as written in the scenario.
        voice_config: The YAML ``voice`` mapping, including ``local`` and
            the selected engine's configuration options.

    Returns:
        A tuple ``(audio_path, duration_seconds)`` suitable for Manim's
        ``add_sound()`` and sequence timing.

    Raises:
        ValueError: If ``voice.local`` is not boolean or Piper's speech
            duration scaling is not positive.
        FileNotFoundError: If the requested local Piper model is missing.
        subprocess.CalledProcessError: If Piper synthesis fails.
    """
    text = " ".join(text.split())
    local = voice_config.get("local", False)
    if not isinstance(local, bool):
        raise ValueError("voice.local must be a YAML boolean (true or false)")

    if local:
        model = voice_config["model"]
        speaker = int(voice_config.get("speaker", 0))
        length_scale = float(voice_config.get("length_scale", 1.0))
        if length_scale <= 0:
            raise ValueError("voice.length_scale must be positive")

        cache_key = f"piper|{model}|{speaker}|{length_scale}|{text}"
        extension = ".wav"
    else:
        voice = voice_config["name"]
        rate = voice_config.get("rate", "+0%")
        # Keep existing Edge TTS MP3s valid after this refactoring.
        cache_key = f"{voice}|{rate}|{text}"
        extension = ".mp3"

    digest = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()[:16]
    AUDIO_CACHE.mkdir(parents=True, exist_ok=True)
    audio_path = AUDIO_CACHE / f"{digest}{extension}"

    if not audio_path.is_file() or audio_path.stat().st_size == 0:
        try:
            if local:
                model_path = ROOT / "assets" / "voices" / f"{model}.onnx"
                config_path = Path(f"{model_path}.json")
                if not model_path.is_file():
                    raise FileNotFoundError(f"Piper model not found: {model_path}")
                if not config_path.is_file():
                    raise FileNotFoundError(f"Piper model config not found: {config_path}")

                subprocess.run(
                    [
                        sys.executable, "-m", "piper",
                        "-m", str(model_path),
                        "-f", str(audio_path),
                        "--speaker", str(speaker),
                        "--length-scale", str(length_scale),
                    ],
                    input=text,
                    text=True,
                    check=True,
                )
            else:
                async def synthesize() -> None:
                    """Request a remote MP3 using the configured Edge TTS voice."""
                    await edge_tts.Communicate(
                        text=text, voice=voice, rate=rate,
                    ).save(str(audio_path))

                asyncio.run(synthesize())
        except Exception:
            audio_path.unlink(missing_ok=True)
            raise

    if local:
        with wave.open(str(audio_path), "rb") as audio:
            duration = audio.getnframes() / audio.getframerate()
    else:
        duration = MP3(str(audio_path)).info.length

    return audio_path, duration

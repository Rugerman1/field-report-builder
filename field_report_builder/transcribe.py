"""Offline speech-to-text with faster-whisper.

The Whisper model is not bundled in the exe.  It downloads once, on first
use, into %LOCALAPPDATA%\\FieldReportBuilder\\models (base.en is about
150 MB) and runs on the CPU with int8 weights after that, with no internet.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

MODEL_SIZES = {
    "tiny.en": "Tiny (75 MB, fastest)",
    "base.en": "Base (150 MB, recommended)",
    "small.en": "Small (480 MB, most accurate)",
}
DEFAULT_MODEL = "base.en"

# Whisper's prompt nudges spelling toward site vocabulary it would otherwise miss.
VOCAB_PROMPT = (
    "Daily report. Station 12+50, subgrade, aggregate base, proof roll, RCP, catch basin, rebar, "
    "formwork, curb and gutter, slump, cylinders, nuclear gauge, skid steer, excavator, RFI."
)


@dataclass
class Transcript:
    text: str
    audio_seconds: float
    seconds_taken: float
    model: str


def models_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "FieldReportBuilder", "models")


def available() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


_cache: dict[str, object] = {}


def load_model(size: str = DEFAULT_MODEL):
    if size not in _cache:
        from faster_whisper import WhisperModel

        _cache[size] = WhisperModel(size, device="cpu", compute_type="int8", download_root=models_dir())
    return _cache[size]


def transcribe(path: str, size: str = DEFAULT_MODEL, progress=None) -> Transcript:
    """Transcribe one audio file.  `progress(fraction)` is called as segments arrive."""
    start = time.perf_counter()
    model = load_model(size)
    segments, info = model.transcribe(path, beam_size=5, vad_filter=True, initial_prompt=VOCAB_PROMPT,
                                      language="en", condition_on_previous_text=False)
    parts = []
    for seg in segments:
        parts.append(seg.text.strip())
        if progress and info.duration:
            progress(min(seg.end / info.duration, 1.0))
    return Transcript(text=" ".join(p for p in parts if p), audio_seconds=float(info.duration or 0),
                      seconds_taken=time.perf_counter() - start, model=size)

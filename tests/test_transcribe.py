import os

import pytest

from field_report_builder import transcribe

AUDIO = os.environ.get("FRB_TEST_AUDIO")


def test_model_choices():
    assert transcribe.DEFAULT_MODEL in transcribe.MODEL_SIZES
    assert transcribe.models_dir().endswith(os.path.join("FieldReportBuilder", "models"))


@pytest.mark.skipif(not AUDIO, reason="set FRB_TEST_AUDIO to a spoken WAV (CI makes one with Windows TTS)")
def test_transcribes_a_spoken_memo():
    t = transcribe.transcribe(AUDIO, "tiny.en")
    text = t.text.lower()
    for word in ("excavator", "laborers", "concrete"):
        assert word in text, (word, t.text)
    assert t.audio_seconds > 3

"""Catch native decoder API breakage before downloading speech model weights."""
import importlib.util
import io
import struct
import wave

import pytest


@pytest.mark.skipif(importlib.util.find_spec('faster_whisper') is None,
                    reason='Optional speech extra is required for the real decoder boundary')
def test_real_whisper_decoder_reads_pcm_without_model_or_network():
    import numpy as np
    from faster_whisper.audio import decode_audio
    pcm = struct.pack('<1600h', *([200, -200] * 800))
    audio = io.BytesIO()
    with wave.open(audio, 'wb') as output:
        output.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        output.writeframes(pcm)
    audio.seek(0)
    decoded = decode_audio(audio)
    assert decoded.shape == (1600,)
    assert decoded.dtype == np.float32
    np.testing.assert_allclose(decoded[:8], np.array([200, -200] * 4) / 32768, atol=1e-7)

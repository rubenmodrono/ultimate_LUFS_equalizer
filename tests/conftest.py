import subprocess
from pathlib import Path

import pytest

from lufs_equalizer.ffmpeg import ffmpeg_path


def make_tone(path: Path, amplitude: float, codec_args: list[str], seconds: int = 12, rate: int = 44100) -> Path:
    subprocess.run(
        [ffmpeg_path(), "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", f"anoisesrc=color=pink:duration={seconds}:amplitude={amplitude}:seed=7",
         "-ac", "2", "-ar", str(rate), *codec_args, str(path)],
        check=True,
    )
    return path


@pytest.fixture
def audio_set(tmp_path):
    d = tmp_path / "music"
    d.mkdir()
    return {
        "quiet_mp3": make_tone(d / "quiet.mp3", 0.2, ["-c:a", "libmp3lame", "-b:a", "320k"]),
        "loud_flac": make_tone(d / "loud.flac", 0.9, ["-c:a", "flac", "-sample_fmt", "s32"], rate=48000),
        "mid_wav": make_tone(d / "mid.wav", 0.4, ["-c:a", "pcm_s24le"]),
        "aiff": make_tone(d / "track.aiff", 0.3, ["-c:a", "pcm_s16be"]),
    }

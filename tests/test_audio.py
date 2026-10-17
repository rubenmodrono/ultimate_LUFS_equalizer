import pytest

from lufs_equalizer import audio


@pytest.mark.parametrize("key", ["quiet_mp3", "loud_flac", "mid_wav", "aiff"])
@pytest.mark.parametrize("target,ceiling", [(-9.0, -1.0), (-12.0, -1.0)])
def test_normalize_hits_target_and_respects_peak(audio_set, tmp_path, key, target, ceiling):
    src = audio_set[key]
    info = audio.probe(src)
    before = audio.measure(src)
    dst = tmp_path / "out" / src.name
    result = audio.normalize(src, dst, before, info, target, ceiling)
    after = audio.measure(dst)
    assert abs(after.integrated - target) <= 0.5
    assert after.true_peak <= ceiling + 0.05
    assert result.after.integrated == pytest.approx(after.integrated, abs=0.05)


def test_output_keeps_format_and_sample_rate(audio_set, tmp_path):
    for src in audio_set.values():
        info = audio.probe(src)
        dst = tmp_path / src.name
        audio.normalize(src, dst, audio.measure(src), info)
        out = audio.probe(dst)
        assert out.codec == info.codec
        assert out.sample_rate == info.sample_rate
        assert out.bits == info.bits or info.codec == "mp3"


def test_original_untouched(audio_set, tmp_path):
    src = audio_set["quiet_mp3"]
    data = src.read_bytes()
    audio.normalize(src, tmp_path / "x.mp3", audio.measure(src), audio.probe(src))
    assert src.read_bytes() == data


def test_linear_gain_when_there_is_headroom(audio_set, tmp_path):
    src = audio_set["quiet_mp3"]
    before = audio.measure(src)
    target = before.integrated + 2  # sube 2 dB: hay margen de pico de sobra
    result = audio.normalize(src, tmp_path / "x.mp3", before, audio.probe(src), target, -1.0)
    assert not result.limited
    assert result.gain_db == pytest.approx(2.0, abs=0.01)

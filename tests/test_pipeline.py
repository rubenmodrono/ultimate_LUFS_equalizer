from lufs_equalizer.pipeline import Job, Settings, Status
from lufs_equalizer.playlists import Playlist, PlaylistEntry


def test_job_collects_finds_moved_files_and_reports(audio_set, tmp_path):
    moved = audio_set["mid_wav"]
    entries = [
        PlaylistEntry(str(audio_set["quiet_mp3"]), "Quiet"),
        PlaylistEntry("D:/Engine Library/Music/mid.wav", "Movido de disco"),
        PlaylistEntry(str(tmp_path / "nope.mp3"), "No existe"),
    ]
    settings = Settings(output_dir=tmp_path / "out", workers=2, copy_originals=True,
                        search_dirs=[moved.parent])
    seen = []
    job = Job(Playlist("PLAN B", entries), settings, lambda t: seen.append(t.status))
    tracks = job.run()

    assert [t.status for t in tracks] == [Status.DONE, Status.DONE, Status.MISSING]
    out = tmp_path / "out" / "PLAN B"
    assert (out / "01 - quiet.mp3").is_file()
    assert (out / "02 - mid.wav").is_file()
    assert (out / "originales" / "01 - quiet.mp3").is_file()
    assert (out / "informe.csv").is_file() and (out / "informe.html").is_file()
    m3u = (out / "PLAN B.m3u8").read_text(encoding="utf-8")
    assert "01 - quiet.mp3" in m3u and "nope" not in m3u
    assert Status.ANALYZING in seen and Status.NORMALIZING in seen


def test_analyze_only_writes_no_audio(audio_set, tmp_path):
    entries = [PlaylistEntry(str(audio_set["aiff"]), "x")]
    job = Job(Playlist("solo", entries), Settings(output_dir=tmp_path, analyze_only=True))
    [t] = job.run()
    assert t.status == Status.ANALYZED and t.before is not None
    assert not list((tmp_path / "solo").glob("*.aiff"))

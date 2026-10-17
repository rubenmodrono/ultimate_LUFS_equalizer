import struct

from lufs_equalizer.playlists import load_playlists


def test_m3u8_with_relative_absolute_and_windows_paths(tmp_path):
    (tmp_path / "a.mp3").write_bytes(b"")
    pl_file = tmp_path / "set.m3u8"
    pl_file.write_text(
        "#EXTM3U\n#EXTINF:300,Artist - Song\na.mp3\n"
        "#EXTINF:200,Otro\nC:/Users/Ruben/Music/b.flac\n"
        "file:///D:/Music/c%20d.wav\n",
        encoding="utf-8",
    )
    [pl] = load_playlists(pl_file)
    assert pl.name == "set"
    assert [e.title for e in pl.entries] == ["Artist - Song", "Otro", "c d"]
    assert pl.entries[0].path == str(tmp_path / "a.mp3")
    assert pl.entries[0].duration == 300
    assert pl.entries[1].path == "C:/Users/Ruben/Music/b.flac"
    assert pl.entries[2].path == "D:/Music/c d.wav"


def test_rekordbox_xml(tmp_path):
    xml = tmp_path / "rekordbox.xml"
    xml.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<DJ_PLAYLISTS Version="1.0.0">
  <COLLECTION Entries="2">
    <TRACK TrackID="1" Name="Lake of Tears" Artist="Cullen Enslin" TotalTime="328"
           Location="file://localhost/D:/Music/Lake%20of%20Tears.m4a"/>
    <TRACK TrackID="2" Name="Fake" Artist="Wehbba" TotalTime="439"
           Location="file://localhost/Users/ruben/Music/Fake.flac"/>
  </COLLECTION>
  <PLAYLISTS>
    <NODE Type="0" Name="ROOT" Count="1">
      <NODE Type="0" Name="Club" Count="1">
        <NODE Name="PLAN B" Type="1" KeyType="0" Entries="2">
          <TRACK Key="2"/><TRACK Key="1"/>
        </NODE>
      </NODE>
    </NODE>
  </PLAYLISTS>
</DJ_PLAYLISTS>""", encoding="utf-8")
    [pl] = load_playlists(xml)
    assert pl.name == "Club / PLAN B"
    assert [e.path for e in pl.entries] == ["/Users/ruben/Music/Fake.flac", "D:/Music/Lake of Tears.m4a"]
    assert pl.entries[0].title == "Wehbba - Fake"


def test_traktor_nml(tmp_path):
    nml = tmp_path / "set.nml"
    nml.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<NML VERSION="19">
  <COLLECTION ENTRIES="1">
    <ENTRY TITLE="Torx" ARTIST="BAUGRUPPE90">
      <LOCATION DIR="/:Users/:Ruben/:Music/:" FILE="Torx.mp3" VOLUME="C:"/>
      <INFO PLAYTIME="367"/>
    </ENTRY>
  </COLLECTION>
  <PLAYLISTS>
    <NODE TYPE="FOLDER" NAME="$ROOT"><SUBNODES>
      <NODE TYPE="PLAYLIST" NAME="Noviembre">
        <PLAYLIST ENTRIES="2" TYPE="LIST">
          <ENTRY><PRIMARYKEY TYPE="TRACK" KEY="C:/:Users/:Ruben/:Music/:Torx.mp3"/></ENTRY>
          <ENTRY><PRIMARYKEY TYPE="TRACK" KEY="D:/:Sets/:Otro.wav"/></ENTRY>
        </PLAYLIST>
      </NODE>
    </SUBNODES></NODE>
  </PLAYLISTS>
</NML>""", encoding="utf-8")
    [pl] = load_playlists(nml)
    assert pl.name == "Noviembre"
    assert pl.entries[0].path == "C:/Users/Ruben/Music/Torx.mp3"
    assert pl.entries[0].title == "BAUGRUPPE90 - Torx"
    assert pl.entries[1].path == "D:/Sets/Otro.wav"


def _tag(name: str, payload: bytes) -> bytes:
    return name.encode("latin-1") + struct.pack(">I", len(payload)) + payload


def test_serato_crate_on_external_drive(tmp_path):
    crate_dir = tmp_path / "_Serato_" / "Subcrates"
    crate_dir.mkdir(parents=True)
    track = "Music/Edvvin - Pump It.mp3"
    data = _tag("vrsn", "1.0/Serato ScratchLive Crate".encode("utf-16-be"))
    data += _tag("otrk", _tag("ptrk", track.encode("utf-16-be")))
    crate = crate_dir / "Club%%Plan B.crate"
    crate.write_bytes(data)
    [pl] = load_playlists(crate)
    assert pl.name == "Club / Plan B"
    assert pl.entries[0].title == "Edvvin - Pump It"
    assert pl.entries[0].path.endswith("Music/Edvvin - Pump It.mp3")


def test_folder_as_playlist(tmp_path):
    for n in ("b.mp3", "a.flac", "notes.txt"):
        (tmp_path / n).write_bytes(b"")
    [pl] = load_playlists(tmp_path)
    assert [e.title for e in pl.entries] == ["a", "b"]

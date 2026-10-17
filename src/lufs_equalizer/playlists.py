"""Lectura de playlists de software de DJ.

Formatos soportados:
- M3U / M3U8 (Rekordbox, Engine DJ, Serato, Traktor, VirtualDJ, Mixxx...)
- Rekordbox XML (Archivo > Exportar colección en formato xml)
- Traktor NML (colección o playlist exportada)
- Serato .crate (carpeta _Serato_/Subcrates)
- Una carpeta con archivos de audio
"""

from __future__ import annotations

import os
import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from urllib.parse import unquote, urlparse

AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".wave", ".aif", ".aiff", ".flac", ".m4a", ".aac", ".alac", ".ogg", ".opus",
}

PLAYLIST_EXTENSIONS = {".m3u", ".m3u8", ".xml", ".nml", ".crate"}


@dataclass
class PlaylistEntry:
    path: str
    title: str = ""
    duration: float | None = None


@dataclass
class Playlist:
    name: str
    entries: list[PlaylistEntry] = field(default_factory=list)


class PlaylistError(Exception):
    pass


def load_playlists(source: str | os.PathLike) -> list[Playlist]:
    """Devuelve todas las playlists que contiene `source`.

    Un M3U o un .crate devuelven una sola; un XML de Rekordbox o un NML de Traktor
    pueden contener muchas y la interfaz deja elegir.
    """
    src = Path(source)
    if src.is_dir():
        return [_load_folder(src)]
    if not src.is_file():
        raise PlaylistError(f"No existe: {src}")
    ext = src.suffix.lower()
    if ext in (".m3u", ".m3u8"):
        return [_load_m3u(src)]
    if ext == ".crate":
        return [_load_serato_crate(src)]
    if ext in (".xml", ".nml"):
        root = ET.parse(src).getroot()
        if root.tag == "DJ_PLAYLISTS":
            return _load_rekordbox_xml(root)
        if root.tag == "NML":
            return _load_traktor_nml(root, src.stem)
        raise PlaylistError("El XML no es de Rekordbox ni de Traktor.")
    raise PlaylistError(f"Formato no soportado: {ext}")


# --- M3U ---------------------------------------------------------------------

def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _load_m3u(path: Path) -> Playlist:
    pl = Playlist(name=path.stem)
    title, duration = "", None
    for line in _read_text(path).splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#EXTINF:"):
            info = line[len("#EXTINF:"):]
            dur, _, title = info.partition(",")
            try:
                duration = float(dur.split()[0])
            except (ValueError, IndexError):
                duration = None
            title = title.strip()
            continue
        if line.startswith("#"):
            continue
        entry_path = _uri_to_path(line)
        if not _is_absolute_any(entry_path):
            entry_path = str((path.parent / entry_path))
        pl.entries.append(PlaylistEntry(entry_path, title or _stem(entry_path), duration))
        title, duration = "", None
    return pl


# --- Rekordbox XML -----------------------------------------------------------

def _load_rekordbox_xml(root: ET.Element) -> list[Playlist]:
    by_id: dict[str, ET.Element] = {}
    by_location: dict[str, ET.Element] = {}
    collection = root.find("COLLECTION")
    if collection is not None:
        for tr in collection.findall("TRACK"):
            by_id[tr.get("TrackID", "")] = tr
            by_location[tr.get("Location", "")] = tr

    playlists: list[Playlist] = []

    def walk(node: ET.Element, prefix: str) -> None:
        for child in node.findall("NODE"):
            name = child.get("Name", "")
            if child.get("Type") == "1":
                key_type = child.get("KeyType", "0")
                pl = Playlist(name=f"{prefix}{name}")
                for ref in child.findall("TRACK"):
                    key = ref.get("Key", "")
                    tr = by_location.get(key) if key_type == "1" else by_id.get(key)
                    location = tr.get("Location") if tr is not None else key
                    if not location:
                        continue
                    path = _uri_to_path(location)
                    title = ""
                    duration = None
                    if tr is not None:
                        artist, track_name = tr.get("Artist", ""), tr.get("Name", "")
                        title = f"{artist} - {track_name}" if artist else track_name
                        duration = _to_float(tr.get("TotalTime"))
                    pl.entries.append(PlaylistEntry(path, title or _stem(path), duration))
                playlists.append(pl)
            else:
                sub = "" if name == "ROOT" else f"{prefix}{name} / "
                walk(child, sub)

    pl_root = root.find("PLAYLISTS")
    if pl_root is not None:
        walk(pl_root, "")
    if not playlists:
        raise PlaylistError("El XML de Rekordbox no contiene playlists.")
    return playlists


# --- Traktor NML -------------------------------------------------------------

def _traktor_path(volume: str, directory: str, filename: str) -> str:
    rel = directory.replace("/:", "/") + filename
    if len(volume) == 2 and volume[1] == ":":  # Windows: "C:"
        return volume + rel
    # macOS: el disco de arranque no lleva /Volumes delante
    if os.name != "nt" and volume and Path(f"/Volumes/{volume}{rel}").exists():
        return f"/Volumes/{volume}{rel}"
    return rel


def _load_traktor_nml(root: ET.Element, fallback_name: str) -> list[Playlist]:
    by_key: dict[str, tuple[str, str, float | None]] = {}
    collection = root.find("COLLECTION")
    if collection is not None:
        for entry in collection.findall("ENTRY"):
            loc = entry.find("LOCATION")
            if loc is None:
                continue
            volume, directory, filename = loc.get("VOLUME", ""), loc.get("DIR", ""), loc.get("FILE", "")
            key = f"{volume}{directory}{filename}"
            artist, title = entry.get("ARTIST", ""), entry.get("TITLE", "")
            info = entry.find("INFO")
            duration = _to_float(info.get("PLAYTIME")) if info is not None else None
            by_key[key] = (
                _traktor_path(volume, directory, filename),
                f"{artist} - {title}" if artist else title,
                duration,
            )

    playlists: list[Playlist] = []
    for node in root.iter("NODE"):
        if node.get("TYPE") != "PLAYLIST":
            continue
        pl = Playlist(name=node.get("NAME", fallback_name))
        container = node.find("PLAYLIST")
        if container is None:
            continue
        for entry in container.findall("ENTRY"):
            pk = entry.find("PRIMARYKEY")
            if pk is None or pk.get("TYPE") != "TRACK":
                continue
            key = pk.get("KEY", "")
            if key in by_key:
                path, title, duration = by_key[key]
            else:
                # KEY = "VOLUMEN/:carpeta/:subcarpeta/:archivo.mp3"
                volume, _, rest = key.partition("/:")
                folders, _, filename = rest.rpartition("/:")
                path = _traktor_path(volume, f"/:{folders}/:" if folders else "/:", filename)
                title, duration = "", None
            pl.entries.append(PlaylistEntry(path, title or _stem(path), duration))
        if pl.entries:
            playlists.append(pl)
    if not playlists and by_key:
        playlists.append(
            Playlist(fallback_name, [PlaylistEntry(p, t or _stem(p), d) for p, t, d in by_key.values()])
        )
    if not playlists:
        raise PlaylistError("El NML de Traktor no contiene tracks.")
    return playlists


# --- Serato .crate -----------------------------------------------------------

def _serato_tags(data: bytes):
    i = 0
    while i + 8 <= len(data):
        tag = data[i:i + 4].decode("latin-1")
        (length,) = struct.unpack(">I", data[i + 4:i + 8])
        yield tag, data[i + 8:i + 8 + length]
        i += 8 + length


def _serato_root(crate: Path) -> Path:
    for parent in crate.parents:
        if parent.name == "_Serato_":
            base = parent.parent
            # En un disco externo _Serato_ está en la raíz; en el disco del sistema
            # está en ~/Music y las rutas son relativas a la raíz del disco.
            if base == Path(base.anchor) or (base.parent == Path("/Volumes")):
                return base
            return Path(base.anchor)
    return Path(crate.anchor)


def _load_serato_crate(path: Path) -> Playlist:
    data = path.read_bytes()
    root = _serato_root(path)
    pl = Playlist(name=path.stem.replace("%%", " / "))
    for tag, payload in _serato_tags(data):
        if tag != "otrk":
            continue
        for sub, value in _serato_tags(payload):
            if sub == "ptrk":
                rel = value.decode("utf-16-be")
                full = str(root / rel)
                pl.entries.append(PlaylistEntry(full, _stem(full)))
    if not pl.entries:
        raise PlaylistError("El crate de Serato está vacío.")
    return pl


# --- Carpeta -----------------------------------------------------------------

def _load_folder(folder: Path) -> Playlist:
    files = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS)
    if not files:
        raise PlaylistError("La carpeta no contiene archivos de audio.")
    return Playlist(folder.name, [PlaylistEntry(str(p), p.stem) for p in files])


# --- Utilidades --------------------------------------------------------------

def _uri_to_path(value: str) -> str:
    if value.lower().startswith("file:"):
        parsed = urlparse(value)
        path = unquote(parsed.path)
        # file://localhost/C:/Music/x.mp3 -> C:/Music/x.mp3
        if len(path) >= 3 and path[0] == "/" and path[2] == ":":
            path = path[1:]
        return path
    return value


def _is_absolute_any(path: str) -> bool:
    return path.startswith("/") or PureWindowsPath(path).is_absolute() or path.startswith("\\\\")


def _stem(path: str) -> str:
    return PureWindowsPath(path).stem if "\\" in path else Path(path).stem


def _to_float(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None

"""Orquesta el trabajo de los agentes sobre cada track de la playlist.

Cada track pasa por tres agentes en orden:
  1. Recolector: localiza el archivo (aunque haya cambiado de disco o carpeta)
     y, si se pide, copia el original a la carpeta de salida.
  2. Analizador: mide LUFS integrados, true peak y rango dinámico.
  3. Normalizador: aplica la ganancia, limita si hace falta y verifica el resultado.

Varios tracks se procesan a la vez (uno por agente en paralelo). Los archivos
originales nunca se modifican.
"""

from __future__ import annotations

import os
import re
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PureWindowsPath
from typing import Callable

from . import audio
from .playlists import AUDIO_EXTENSIONS, Playlist


class Status(str, Enum):
    PENDING = "En cola"
    COLLECTING = "Recogiendo"
    MISSING = "No encontrado"
    ANALYZING = "Analizando"
    NORMALIZING = "Normalizando"
    DONE = "Listo"
    ANALYZED = "Analizado"
    ERROR = "Error"
    CANCELLED = "Cancelado"


@dataclass
class Settings:
    target_lufs: float = -9.0
    ceiling_dbtp: float = -1.0
    workers: int = max(1, min(8, (os.cpu_count() or 2) - 1))
    output_dir: Path = Path.home() / "Music" / "LUFS Equalizer"
    copy_originals: bool = False
    analyze_only: bool = False
    search_dirs: list[Path] = field(default_factory=list)


@dataclass
class Track:
    index: int
    title: str
    playlist_path: str
    source: Path | None = None
    status: Status = Status.PENDING
    message: str = ""
    info: audio.StreamInfo | None = None
    before: audio.Loudness | None = None
    after: audio.Loudness | None = None
    gain_db: float | None = None
    limited: bool = False
    limiter_reduction_db: float = 0.0
    output: Path | None = None
    agent: str = ""


class FileFinder:
    """Busca por nombre de archivo en las carpetas indicadas (se indexan una vez)."""

    def __init__(self, folders: list[Path]):
        self._folders = [Path(f) for f in folders if Path(f).is_dir()]
        self._index: dict[str, list[Path]] | None = None
        self._stems: dict[str, list[Path]] | None = None
        self._lock = threading.Lock()

    def _build(self) -> None:
        names: dict[str, list[Path]] = {}
        stems: dict[str, list[Path]] = {}
        for folder in self._folders:
            for dirpath, _dirs, files in os.walk(folder):
                for f in files:
                    p = Path(dirpath) / f
                    if p.suffix.lower() not in AUDIO_EXTENSIONS:
                        continue
                    names.setdefault(f.lower(), []).append(p)
                    stems.setdefault(p.stem.lower(), []).append(p)
        self._index, self._stems = names, stems

    def find(self, original: str) -> Path | None:
        if not self._folders:
            return None
        with self._lock:
            if self._index is None:
                self._build()
        win = PureWindowsPath(original)
        name = win.name if "\\" in original or ":" in original[:3] else Path(original).name
        hits = self._index.get(name.lower()) or self._stems.get(Path(name).stem.lower())
        return hits[0] if hits else None


def resolve_path(original: str, finder: FileFinder) -> Path | None:
    candidates = [original]
    if os.name != "nt" and "\\" in original:
        candidates.append(original.replace("\\", "/"))
    if os.name == "nt":
        candidates.append(original.replace("/", "\\"))
    for c in candidates:
        p = Path(c)
        if p.is_file():
            return p
    return finder.find(original)


_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def output_name(track: Track, ext: str | None = None) -> str:
    stem = track.source.stem if track.source else track.title
    stem = _UNSAFE.sub("_", stem).strip(" .") or f"track {track.index}"
    return f"{track.index:02d} - {stem}{ext or track.source.suffix}"


class Job:
    """Procesa una playlist. Llama a `on_update(track)` cada vez que un track cambia."""

    def __init__(
        self,
        playlist: Playlist,
        settings: Settings,
        on_update: Callable[[Track], None] | None = None,
    ):
        self.playlist = playlist
        self.settings = settings
        self.on_update = on_update or (lambda t: None)
        self.tracks = [
            Track(i + 1, e.title, e.path) for i, e in enumerate(playlist.entries)
        ]
        self._cancel = threading.Event()
        self._finder = FileFinder(settings.search_dirs)
        self.out_dir = Path(settings.output_dir) / _UNSAFE.sub("_", playlist.name).strip(" .")

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def run(self) -> list[Track]:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        with ThreadPoolExecutor(max_workers=max(1, self.settings.workers), thread_name_prefix="agent") as pool:
            futures = [pool.submit(self._process, t) for t in self.tracks]
            for f in futures:
                f.result()
        from .report import write_reports

        write_reports(self)
        return self.tracks

    def _set(self, track: Track, status: Status, message: str = "") -> None:
        track.status = status
        track.message = message
        self.on_update(track)

    def _process(self, track: Track) -> None:
        if self.cancelled:
            self._set(track, Status.CANCELLED)
            return
        # Los hilos se llaman agent_0, agent_1...
        track.agent = f"Agente {int(threading.current_thread().name.rsplit('_', 1)[-1]) + 1}"
        try:
            # 1. Recolector
            self._set(track, Status.COLLECTING)
            src = resolve_path(track.playlist_path, self._finder)
            if src is None:
                self._set(track, Status.MISSING, "No está en la ruta de la playlist ni en las carpetas de búsqueda.")
                return
            track.source = src
            if self.settings.copy_originals:
                orig_dir = self.out_dir / "originales"
                orig_dir.mkdir(exist_ok=True)
                shutil.copy2(src, orig_dir / output_name(track))

            # 2. Analizador
            if self.cancelled:
                self._set(track, Status.CANCELLED)
                return
            self._set(track, Status.ANALYZING)
            track.info = audio.probe(src)
            track.before = audio.measure(src)
            track.gain_db = self.settings.target_lufs - track.before.integrated
            if self.settings.analyze_only:
                self._set(track, Status.ANALYZED)
                return

            # 3. Normalizador
            if self.cancelled:
                self._set(track, Status.CANCELLED)
                return
            self._set(track, Status.NORMALIZING)
            dst = self.out_dir / output_name(track)
            if dst.resolve() == src.resolve():  # jamás sobrescribir el original
                dst = dst.with_name(dst.stem + " (norm)" + dst.suffix)
            result = audio.normalize(
                src, dst, track.before, track.info,
                self.settings.target_lufs, self.settings.ceiling_dbtp,
            )
            track.output = dst
            track.after = result.after
            track.gain_db = result.gain_db
            track.limited = result.limited
            track.limiter_reduction_db = result.limiter_reduction_db
            note = ""
            if result.limited:
                note = f"Limitado {result.limiter_reduction_db:.1f} dB para respetar el pico"
                if result.limiter_reduction_db > 4:
                    note += " (mucho: revisa cómo suena)"
            self._set(track, Status.DONE, note)
        except Exception as exc:  # cada track falla por separado, el resto sigue
            self._set(track, Status.ERROR, str(exc))

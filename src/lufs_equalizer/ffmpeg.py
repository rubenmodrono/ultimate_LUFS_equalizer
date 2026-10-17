"""Localiza el ejecutable de ffmpeg y lo lanza sin abrir ventanas de consola."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def ffmpeg_path() -> str:
    """Orden de búsqueda: variable LUFS_FFMPEG, binario empaquetado, PATH, imageio-ffmpeg."""
    env = os.environ.get("LUFS_FFMPEG")
    if env and Path(env).is_file():
        return env
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if bundle_dir:
        bundled = Path(bundle_dir) / exe
        if bundled.is_file():
            return str(bundled)
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # pragma: no cover - depende del entorno
        raise RuntimeError(
            "No se encuentra ffmpeg. Instálalo o define la variable LUFS_FFMPEG."
        ) from exc


def run_ffmpeg(args: list[str], timeout: float | None = None) -> subprocess.CompletedProcess:
    """Ejecuta ffmpeg y devuelve el proceso terminado (stderr como texto)."""
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.run(
        [ffmpeg_path(), "-hide_banner", "-nostdin", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        **kwargs,
    )

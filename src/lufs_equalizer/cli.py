"""Uso por línea de comandos: lufs-equalizer playlist.m3u8 -o carpeta"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .pipeline import Job, Settings, Status
from .playlists import PlaylistError, load_playlists


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lufs-equalizer", description="Normaliza los tracks de una playlist de DJ.")
    ap.add_argument("playlist", help="M3U/M3U8, XML de Rekordbox, NML de Traktor, .crate de Serato o carpeta")
    ap.add_argument("-o", "--output", type=Path, default=Settings().output_dir, help="carpeta de salida")
    ap.add_argument("-p", "--name", help="nombre de la playlist (si el archivo tiene varias)")
    ap.add_argument("-t", "--target", type=float, default=-9.0, help="LUFS integrados objetivo (por defecto -9)")
    ap.add_argument("-c", "--ceiling", type=float, default=-1.0, help="true peak máximo en dBTP (por defecto -1)")
    ap.add_argument("-j", "--workers", type=int, default=Settings().workers, help="agentes en paralelo")
    ap.add_argument("-s", "--search", type=Path, action="append", default=[], help="carpeta donde buscar archivos que falten")
    ap.add_argument("--copy-originals", action="store_true", help="copia también los originales a la carpeta de salida")
    ap.add_argument("--analyze-only", action="store_true", help="solo analiza, no genera archivos")
    args = ap.parse_args(argv)

    try:
        playlists = load_playlists(args.playlist)
    except (PlaylistError, OSError) as exc:
        print(f"No se pudo leer la playlist: {exc}", file=sys.stderr)
        return 2
    if args.name:
        playlists = [p for p in playlists if p.name == args.name or p.name.endswith(f"/ {args.name}")]
        if not playlists:
            print(f"No hay ninguna playlist llamada {args.name!r}", file=sys.stderr)
            return 2
    elif len(playlists) > 1:
        print("El archivo contiene varias playlists; elige una con --name:", file=sys.stderr)
        for p in playlists:
            print(f"  {p.name} ({len(p.entries)} tracks)", file=sys.stderr)
        return 2

    settings = Settings(
        target_lufs=args.target, ceiling_dbtp=args.ceiling, workers=args.workers,
        output_dir=args.output, copy_originals=args.copy_originals,
        analyze_only=args.analyze_only, search_dirs=args.search,
    )

    def on_update(t):
        if t.status in (Status.DONE, Status.ANALYZED, Status.MISSING, Status.ERROR):
            extra = ""
            if t.before:
                extra = f"{t.before.integrated:6.1f} LUFS"
            if t.after:
                extra += f" -> {t.after.integrated:6.1f} LUFS, pico {t.after.true_peak:5.1f} dBTP"
            print(f"[{t.index:02d}] {t.status.value:<13} {t.title}  {extra}  {t.message}".rstrip(), flush=True)

    job = Job(playlists[0], settings, on_update)
    tracks = job.run()
    bad = [t for t in tracks if t.status in (Status.MISSING, Status.ERROR)]
    print(f"\nResultado en: {job.out_dir}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

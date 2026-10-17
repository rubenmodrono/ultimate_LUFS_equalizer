"""Medición de sonoridad (EBU R128 / ITU-R BS.1770) y normalización con ffmpeg."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

from .ffmpeg import run_ffmpeg


class AudioError(Exception):
    pass


@dataclass
class StreamInfo:
    codec: str
    sample_rate: int
    channels: str
    sample_fmt: str
    bits: int | None
    bitrate_kbps: int | None
    duration: float | None
    has_cover: bool


@dataclass
class Loudness:
    integrated: float  # LUFS
    true_peak: float  # dBTP
    lra: float  # LU


@dataclass
class NormalizeResult:
    gain_db: float
    limited: bool
    limiter_reduction_db: float
    after: Loudness


# --- Análisis ----------------------------------------------------------------

_STREAM_RE = re.compile(r"Stream #\d+:\d+.*?: Audio: (?P<codec>[\w-]+).*?, (?P<sr>\d+) Hz, (?P<rest>.*)")
_VIDEO_RE = re.compile(r"Stream #\d+:\d+.*?: Video: ")
_DURATION_RE = re.compile(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)")


def probe(path: str | Path) -> StreamInfo:
    proc = run_ffmpeg(["-i", str(path)])
    text = proc.stderr
    m = _STREAM_RE.search(text)
    if not m:
        raise AudioError(_last_error(text) or "No se encuentra pista de audio.")
    parts = [p.strip() for p in m.group("rest").split(",")]
    channels = parts[0] if parts else ""
    sample_fmt = parts[1].split(" ")[0] if len(parts) > 1 else ""
    bits = None
    bm = re.search(r"\((\d+) bit\)", m.group("rest"))
    if bm:
        bits = int(bm.group(1))
    elif sample_fmt.startswith("s16"):
        bits = 16
    elif sample_fmt.startswith("s32"):
        bits = 32
    rm = re.search(r"(\d+) kb/s", m.group("rest"))
    dm = _DURATION_RE.search(text)
    duration = None
    if dm:
        h, mi, s = dm.groups()
        duration = int(h) * 3600 + int(mi) * 60 + float(s)
    return StreamInfo(
        codec=m.group("codec"),
        sample_rate=int(m.group("sr")),
        channels=channels,
        sample_fmt=sample_fmt,
        bits=bits,
        bitrate_kbps=int(rm.group(1)) if rm else None,
        duration=duration,
        has_cover=bool(_VIDEO_RE.search(text)),
    )


def _parse_ebur128(text: str) -> Loudness:
    summary = text[text.rfind("Summary:"):]
    i = re.search(r"I:\s+(-?[\d.]+|-inf) LUFS", summary)
    lra = re.search(r"LRA:\s+(-?[\d.]+) LU", summary)
    peak = re.search(r"Peak:\s+(-?[\d.]+|-inf) dBFS", summary)
    if not i or not peak:
        raise AudioError(_last_error(text) or "No se pudo medir la sonoridad.")
    return Loudness(
        integrated=float(i.group(1)),
        true_peak=float(peak.group(1)),
        lra=float(lra.group(1)) if lra else 0.0,
    )


def measure(path: str | Path, pre_filter: str | None = None) -> Loudness:
    """Mide sonoridad integrada, true peak y LRA del archivo (opcionalmente tras un filtro)."""
    chain = "ebur128=peak=true:framelog=quiet"
    if pre_filter:
        chain = f"{pre_filter},{chain}"
    proc = run_ffmpeg(["-nostats", "-i", str(path), "-map", "0:a:0", "-af", chain, "-f", "null", "-"])
    if proc.returncode != 0:
        raise AudioError(_last_error(proc.stderr) or "ffmpeg falló al analizar.")
    loud = _parse_ebur128(proc.stderr)
    if math.isinf(loud.integrated):
        raise AudioError("El archivo es silencio.")
    return loud


# --- Normalización -----------------------------------------------------------

def _db_to_lin(db: float) -> float:
    return 10 ** (db / 20)


def _gain_filter(gain_db: float, limit_db: float | None, sample_rate: int) -> str:
    chain = f"volume={gain_db:.2f}dB"
    if limit_db is not None:
        # El limitador trabaja sobremuestreado x4 para controlar también los picos
        # entre muestras (true peak), y vuelve a la frecuencia original.
        limit = min(1.0, max(0.0625, _db_to_lin(limit_db)))
        chain += (
            f",aresample={sample_rate * 4}"
            f",alimiter=limit={limit:.5f}:level=false:attack=1:release=60:asc=true"
            f",aresample={sample_rate}"
        )
    return chain


def _encoder_args(info: StreamInfo, out_ext: str) -> list[str]:
    ext = out_ext.lower()
    codec = info.codec
    if ext == ".mp3":
        kbps = info.bitrate_kbps or 320
        kbps = min(320, max(128, kbps))
        return ["-c:a", "libmp3lame", "-b:a", f"{kbps}k", "-id3v2_version", "3"]
    if ext == ".flac":
        fmt = "s16" if (info.bits or 16) <= 16 else "s32"
        return ["-c:a", "flac", "-sample_fmt", fmt]
    if ext in (".wav", ".wave", ".aif", ".aiff"):
        big = ext in (".aif", ".aiff")
        if codec.startswith("pcm_"):
            target = codec
            if big and target.endswith("le"):
                target = target[:-2] + "be"
            if not big and target.endswith("be"):
                target = target[:-2] + "le"
        else:
            depth = 24 if (info.bits or 16) > 16 else 16
            target = f"pcm_s{depth}{'be' if big else 'le'}"
        return ["-c:a", target]
    if ext in (".m4a", ".aac", ".alac"):
        if codec == "alac":
            return ["-c:a", "alac"]
        kbps = info.bitrate_kbps or 256
        return ["-c:a", "aac", "-b:a", f"{min(320, max(128, kbps))}k"]
    if ext == ".ogg":
        return ["-c:a", "libvorbis", "-q:a", "8"]
    if ext == ".opus":
        return ["-c:a", "libopus", "-b:a", f"{info.bitrate_kbps or 192}k"]
    raise AudioError(f"Formato de salida no soportado: {ext}")


def _render(src: Path, dst: Path, info: StreamInfo, chain: str) -> None:
    ext = dst.suffix.lower()
    tmp = dst.with_name(dst.stem + ".part" + dst.suffix)

    def build(keep_cover: bool) -> list[str]:
        args = ["-y", "-i", str(src), "-map", "0:a:0"]
        if keep_cover:
            args += ["-map", "0:v:0?", "-c:v", "copy", "-disposition:v:0", "attached_pic"]
        args += ["-map_metadata", "0", "-af", chain, "-ar", str(info.sample_rate)]
        args += _encoder_args(info, ext)
        args.append(str(tmp))
        return args

    keep_cover = info.has_cover and ext in (".mp3", ".m4a", ".flac")
    proc = run_ffmpeg(build(keep_cover))
    if proc.returncode != 0 and keep_cover:
        # Algunas portadas no se pueden copiar; se reintenta sin ellas.
        proc = run_ffmpeg(build(False))
    if proc.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise AudioError(_last_error(proc.stderr) or "ffmpeg falló al escribir el archivo.")
    tmp.replace(dst)


def normalize(
    src: str | Path,
    dst: str | Path,
    before: Loudness,
    info: StreamInfo,
    target_lufs: float = -9.0,
    ceiling_dbtp: float = -1.0,
    tolerance: float = 0.5,
) -> NormalizeResult:
    """Lleva `src` a `target_lufs` con true peak <= `ceiling_dbtp` y lo escribe en `dst`.

    Primero intenta solo ganancia lineal. Si el pico resultante supera el techo,
    añade un limitador true-peak y compensa la pérdida de sonoridad que provoca.
    """
    src, dst = Path(src), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    gain = target_lufs - before.integrated
    lossy = dst.suffix.lower() in (".mp3", ".m4a", ".aac", ".ogg", ".opus") and info.codec != "alac"
    # Los códecs con pérdida suben un poco el pico al decodificar: margen extra.
    margin = 0.3 if lossy else 0.1

    if before.true_peak + gain <= ceiling_dbtp - margin:
        _render(src, dst, info, _gain_filter(gain, None, info.sample_rate))
        after = measure(dst)
        return NormalizeResult(gain, False, 0.0, after)

    limit_db = ceiling_dbtp - margin - 0.2
    after = None
    for _ in range(3):
        chain = _gain_filter(gain, limit_db, info.sample_rate)
        _render(src, dst, info, chain)
        after = measure(dst)
        off_target = target_lufs - after.integrated
        over_peak = after.true_peak - ceiling_dbtp
        if over_peak > 0:
            limit_db -= over_peak + 0.1
            continue
        if abs(off_target) <= tolerance:
            break
        gain += off_target
    assert after is not None
    reduction = max(0.0, before.true_peak + gain - ceiling_dbtp)
    return NormalizeResult(gain, True, reduction, after)


def _last_error(stderr: str) -> str:
    lines = [ln.strip() for ln in stderr.splitlines() if ln.strip()]
    for ln in reversed(lines):
        low = ln.lower()
        if "error" in low or "invalid" in low or "no such file" in low:
            return ln
    return lines[-1] if lines else ""

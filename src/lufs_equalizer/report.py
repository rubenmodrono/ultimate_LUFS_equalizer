"""Informe del set: CSV, HTML y una playlist M3U8 con los tracks normalizados."""

from __future__ import annotations

import csv
import html
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .pipeline import Job, Track


def _fmt(value: float | None, digits: int = 1) -> str:
    return "" if value is None else f"{value:.{digits}f}"


def _row(t: "Track") -> dict[str, str]:
    return {
        "#": str(t.index),
        "Track": t.title,
        "Formato": t.source.suffix.lstrip(".").upper() if t.source else "",
        "Hz": str(t.info.sample_rate) if t.info else "",
        "LUFS antes": _fmt(t.before.integrated if t.before else None),
        "Pico antes (dBTP)": _fmt(t.before.true_peak if t.before else None),
        "LRA (LU)": _fmt(t.before.lra if t.before else None),
        "Ganancia (dB)": (f"{t.gain_db:+.1f}" if t.gain_db is not None else ""),
        "LUFS después": _fmt(t.after.integrated if t.after else None),
        "Pico después (dBTP)": _fmt(t.after.true_peak if t.after else None),
        "Limitador": "sí" if t.limited else "",
        "Estado": t.status.value,
        "Notas": t.message,
        "Original": str(t.source or t.playlist_path),
        "Normalizado": t.output.name if t.output else "",
    }


def write_reports(job: "Job") -> None:
    out = job.out_dir
    rows = [_row(t) for t in job.tracks]

    with open(out / "informe.csv", "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else ["#"], delimiter=";")
        writer.writeheader()
        writer.writerows(rows)

    done = [t for t in job.tracks if t.output]
    if done:
        with open(out / f"{out.name}.m3u8", "w", encoding="utf-8") as fh:
            fh.write("#EXTM3U\n")
            for t in done:
                dur = int(t.info.duration) if t.info and t.info.duration else -1
                fh.write(f"#EXTINF:{dur},{t.title}\n{t.output.name}\n")

    s = job.settings
    cols = ["#", "Track", "Formato", "LUFS antes", "Pico antes (dBTP)", "LRA (LU)", "Ganancia (dB)",
            "LUFS después", "Pico después (dBTP)", "Estado", "Notas"]
    head = "".join(f"<th>{html.escape(c)}</th>" for c in cols)
    body = "".join(
        "<tr class='{cls}'>{cells}</tr>".format(
            cls=t.status.name.lower(),
            cells="".join(f"<td>{html.escape(r[c])}</td>" for c in cols),
        )
        for t, r in zip(job.tracks, rows)
    )
    ok = sum(1 for t in job.tracks if t.output)
    page = f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(job.playlist.name)} · informe</title>
<style>
body{{font-family:system-ui,sans-serif;background:#121214;color:#e8e8ea;margin:24px}}
h1{{font-size:20px;margin:0 0 4px}} p{{color:#a0a0a8;margin:0 0 16px}}
table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{padding:6px 8px;border-bottom:1px solid #2a2a30;text-align:left;white-space:nowrap}}
td:nth-child(2){{white-space:normal}} th{{color:#a0a0a8;font-weight:500}}
tr.error td,tr.missing td{{color:#ff7b72}} tr.done td:nth-child(8){{color:#7ee787}}
</style></head><body>
<h1>{html.escape(job.playlist.name)}</h1>
<p>Objetivo {s.target_lufs:.1f} LUFS · pico máximo {s.ceiling_dbtp:.1f} dBTP · {ok}/{len(job.tracks)} tracks normalizados · {datetime.now():%d/%m/%Y %H:%M}</p>
<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>
</body></html>"""
    (out / "informe.html").write_text(page, encoding="utf-8")

# PyInstaller: genera la app standalone con ffmpeg dentro.
#   pyinstaller packaging/lufs_equalizer.spec
import os
from pathlib import Path

import imageio_ffmpeg

ffmpeg_src = imageio_ffmpeg.get_ffmpeg_exe()
ffmpeg_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
root = Path(SPECPATH).parent
staged = Path(workpath) / ffmpeg_name
staged.parent.mkdir(parents=True, exist_ok=True)
staged.write_bytes(Path(ffmpeg_src).read_bytes())
staged.chmod(0o755)

a = Analysis(
    [str(root / "packaging" / "launch_gui.py")],
    pathex=[str(root / "src")],
    binaries=[(str(staged), ".")],
    excludes=[
        "tkinter",
        # Módulos de Qt que la app no usa (reducen mucho el tamaño)
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebChannel",
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.Qt3DCore",
        "PySide6.QtMultimedia", "PySide6.QtPdf", "PySide6.QtCharts", "PySide6.QtDataVisualization",
        "PySide6.QtNetwork", "PySide6.QtOpenGL", "PySide6.QtSql", "PySide6.QtTest",
    ],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Ultimate LUFS Equalizer",
    console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Ultimate LUFS Equalizer")
app = BUNDLE(
    coll,
    name="Ultimate LUFS Equalizer.app",
    bundle_identifier="com.rubenmodrono.lufsequalizer",
) if os.sys.platform == "darwin" else None

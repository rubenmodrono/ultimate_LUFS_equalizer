"""Interfaz de escritorio (PySide6)."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..pipeline import Job, Settings, Status, Track
from ..playlists import PLAYLIST_EXTENSIONS, Playlist, PlaylistError, load_playlists

COLUMNS = ["#", "Track", "Formato", "Agente", "Estado", "LUFS antes", "Pico antes",
           "Ganancia", "LUFS después", "Pico después", "Notas"]

STATUS_COLORS = {
    Status.DONE: "#7ee787",
    Status.ANALYZED: "#7ee787",
    Status.MISSING: "#ff7b72",
    Status.ERROR: "#ff7b72",
    Status.CANCELLED: "#8b8b93",
    Status.PENDING: "#8b8b93",
}

STYLE = """
QWidget { font-size: 13px; }
QFrame#card { background: #1b1b1f; border: 1px solid #2a2a30; border-radius: 8px; }
QLabel#title { font-size: 20px; font-weight: 600; }
QLabel#muted { color: #9a9aa3; }
QLabel#step { color: #c9a227; font-weight: 600; }
QLabel#drop { border: 1px dashed #3a3a42; border-radius: 8px; color: #9a9aa3; padding: 18px; }
QPushButton { background: #26262c; border: 1px solid #34343c; border-radius: 6px; padding: 7px 14px; }
QPushButton:hover { background: #2f2f36; }
QPushButton:disabled { color: #5a5a62; }
QPushButton#primary { background: #c9a227; color: #121214; border: none; font-weight: 600; padding: 9px 22px; }
QPushButton#primary:hover { background: #d8b23a; }
QPushButton#primary:disabled { background: #4a4330; color: #8a8270; }
QTableWidget { background: #151518; border: 1px solid #2a2a30; border-radius: 8px; gridline-color: #232328; }
QHeaderView::section { background: #1b1b1f; color: #9a9aa3; border: none; border-bottom: 1px solid #2a2a30; padding: 6px; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QListWidget { background: #151518; border: 1px solid #34343c; border-radius: 6px; padding: 4px 6px; }
QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #4a4a52; border-radius: 3px; background: #151518; }
QCheckBox::indicator:checked { background: #c9a227; border-color: #c9a227; }
QProgressBar { background: #151518; border: 1px solid #2a2a30; border-radius: 6px; text-align: center; height: 18px; }
QProgressBar::chunk { background: #c9a227; border-radius: 5px; }
"""


class Bridge(QObject):
    """Lleva los eventos de los agentes (otros hilos) al hilo de la interfaz."""

    track_updated = Signal(object)
    finished = Signal()
    failed = Signal(str)


def _card() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(10)
    return frame, layout


def _label(text: str, name: str | None = None) -> QLabel:
    lbl = QLabel(text)
    if name:
        lbl.setObjectName(name)
    return lbl


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Ultimate LUFS Equalizer")
        self.resize(1180, 760)
        self.setAcceptDrops(True)
        self.store = QSettings("rubenmodrono", "UltimateLUFSEqualizer")
        self.playlists: list[Playlist] = []
        self.job: Job | None = None
        self.bridge = Bridge()
        self.bridge.track_updated.connect(self._on_track)
        self.bridge.finished.connect(self._on_finished)
        self.bridge.failed.connect(self._on_failed)
        self._build()
        self._load_prefs()

    # --- Construcción --------------------------------------------------------

    def _build(self) -> None:
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(12)

        head = QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(_label("Ultimate LUFS Equalizer", "title"))
        head.addWidget(_label(
            "Carga la playlist de tu set y todos los tracks saldrán al mismo volumen, "
            "juntos en una carpeta. Los originales no se tocan.", "muted"))
        outer.addLayout(head)

        top = QHBoxLayout()
        top.setSpacing(12)
        top.addWidget(self._build_playlist_card(), 3)
        top.addWidget(self._build_settings_card(), 4)
        outer.addLayout(top)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(len(COLUMNS) - 1, QHeaderView.Stretch)
        outer.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setFormat("%v / %m tracks")
        self.progress.setValue(0)
        self.summary = _label("", "muted")
        self.open_btn = QPushButton("Abrir carpeta")
        self.open_btn.clicked.connect(self._open_output)
        self.open_btn.setEnabled(False)
        self.report_btn = QPushButton("Ver informe")
        self.report_btn.clicked.connect(self._open_report)
        self.report_btn.setEnabled(False)
        self.start_btn = QPushButton("Normalizar set")
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self._start_or_cancel)
        self.start_btn.setEnabled(False)
        bottom.addWidget(self.progress, 2)
        bottom.addWidget(self.summary, 2)
        bottom.addWidget(self.open_btn)
        bottom.addWidget(self.report_btn)
        bottom.addWidget(self.start_btn)
        outer.addLayout(bottom)

        self.setCentralWidget(root)

    def _build_playlist_card(self) -> QFrame:
        frame, lay = _card()
        lay.addWidget(_label("1 · Playlist", "step"))
        self.drop = _label(
            "Arrastra aquí la playlist exportada de tu software\n"
            "M3U / M3U8 · Rekordbox XML · Traktor NML · Serato .crate · o una carpeta", "drop")
        self.drop.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.drop)
        row = QHBoxLayout()
        load_btn = QPushButton("Elegir archivo…")
        load_btn.clicked.connect(self._pick_playlist)
        folder_btn = QPushButton("Elegir carpeta…")
        folder_btn.clicked.connect(self._pick_folder_as_playlist)
        row.addWidget(load_btn)
        row.addWidget(folder_btn)
        row.addStretch()
        lay.addLayout(row)
        self.playlist_combo = QComboBox()
        self.playlist_combo.setVisible(False)
        self.playlist_combo.currentIndexChanged.connect(self._show_playlist)
        lay.addWidget(self.playlist_combo)
        self.playlist_info = _label("", "muted")
        lay.addWidget(self.playlist_info)
        lay.addStretch()
        return frame

    def _build_settings_card(self) -> QFrame:
        frame, lay = _card()
        lay.addWidget(_label("2 · Ajustes", "step"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)

        self.target = QDoubleSpinBox()
        self.target.setRange(-23.0, -5.0)
        self.target.setSingleStep(0.5)
        self.target.setDecimals(1)
        self.target.setSuffix(" LUFS")
        self.target.setToolTip("Sonoridad integrada de todos los tracks. En club se suele usar entre -10 y -8.")
        self.ceiling = QDoubleSpinBox()
        self.ceiling.setRange(-3.0, -0.1)
        self.ceiling.setSingleStep(0.1)
        self.ceiling.setDecimals(1)
        self.ceiling.setSuffix(" dBTP")
        self.ceiling.setToolTip("Pico real máximo. -1 dBTP evita saturar el mezclador y el equipo.")
        self.workers = QSpinBox()
        self.workers.setRange(1, 16)
        self.workers.setToolTip("Cuántos tracks se procesan a la vez.")

        grid.addWidget(_label("Volumen objetivo"), 0, 0)
        grid.addWidget(self.target, 0, 1)
        grid.addWidget(_label("Pico máximo"), 0, 2)
        grid.addWidget(self.ceiling, 0, 3)
        grid.addWidget(_label("Agentes en paralelo"), 0, 4)
        grid.addWidget(self.workers, 0, 5)

        self.output = QLineEdit()
        out_btn = QPushButton("Cambiar…")
        out_btn.clicked.connect(self._pick_output)
        grid.addWidget(_label("Guardar en"), 1, 0)
        grid.addWidget(self.output, 1, 1, 1, 4)
        grid.addWidget(out_btn, 1, 5)

        self.copy_originals = QCheckBox("Copiar también los originales a la carpeta")
        self.analyze_only = QCheckBox("Solo analizar (no crear archivos)")
        self.analyze_only.toggled.connect(self._update_start_label)
        grid.addWidget(self.copy_originals, 2, 0, 1, 3)
        grid.addWidget(self.analyze_only, 2, 3, 1, 3)
        lay.addLayout(grid)

        lay.addWidget(_label(
            "Si algún archivo ha cambiado de sitio, los agentes lo buscan en estas carpetas:", "muted"))
        srow = QHBoxLayout()
        self.search_list = QListWidget()
        self.search_list.setMaximumHeight(64)
        sbtns = QVBoxLayout()
        add_btn = QPushButton("Añadir…")
        add_btn.clicked.connect(self._add_search_dir)
        rm_btn = QPushButton("Quitar")
        rm_btn.clicked.connect(self._remove_search_dir)
        sbtns.addWidget(add_btn)
        sbtns.addWidget(rm_btn)
        srow.addWidget(self.search_list, 1)
        srow.addLayout(sbtns)
        lay.addLayout(srow)
        return frame

    # --- Preferencias --------------------------------------------------------

    def _load_prefs(self) -> None:
        d = Settings()
        self.target.setValue(float(self.store.value("target", d.target_lufs)))
        self.ceiling.setValue(float(self.store.value("ceiling", d.ceiling_dbtp)))
        self.workers.setValue(int(self.store.value("workers", d.workers)))
        self.output.setText(str(self.store.value("output", str(d.output_dir))))
        self.copy_originals.setChecked(self.store.value("copy_originals", False) in (True, "true"))
        for p in self.store.value("search_dirs", []) or []:
            self.search_list.addItem(p)

    def _save_prefs(self) -> None:
        self.store.setValue("target", self.target.value())
        self.store.setValue("ceiling", self.ceiling.value())
        self.store.setValue("workers", self.workers.value())
        self.store.setValue("output", self.output.text())
        self.store.setValue("copy_originals", self.copy_originals.isChecked())
        self.store.setValue("search_dirs", self._search_dirs())

    def _search_dirs(self) -> list[str]:
        return [self.search_list.item(i).text() for i in range(self.search_list.count())]

    # --- Playlist ------------------------------------------------------------

    def dragEnterEvent(self, event):  # noqa: N802 (API de Qt)
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):  # noqa: N802
        urls = event.mimeData().urls()
        if urls:
            self._load(urls[0].toLocalFile())

    def _pick_playlist(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(PLAYLIST_EXTENSIONS))
        path, _ = QFileDialog.getOpenFileName(self, "Elegir playlist", "", f"Playlists ({exts});;Todos (*)")
        if path:
            self._load(path)

    def _pick_folder_as_playlist(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Elegir carpeta con los tracks")
        if path:
            self._load(path)

    def _load(self, path: str) -> None:
        if self.job is not None:
            return
        try:
            self.playlists = load_playlists(path)
        except (PlaylistError, OSError, Exception) as exc:  # XML mal formado, permisos...
            QMessageBox.warning(self, "No se pudo leer la playlist", str(exc))
            return
        self.drop.setText(Path(path).name)
        self.playlist_combo.blockSignals(True)
        self.playlist_combo.clear()
        for p in self.playlists:
            self.playlist_combo.addItem(f"{p.name}  ({len(p.entries)} tracks)")
        self.playlist_combo.blockSignals(False)
        self.playlist_combo.setVisible(len(self.playlists) > 1)
        self._show_playlist(0)

    def _current_playlist(self) -> Playlist | None:
        i = self.playlist_combo.currentIndex()
        if not self.playlists:
            return None
        return self.playlists[max(0, i)]

    def _show_playlist(self, _index: int) -> None:
        pl = self._current_playlist()
        if pl is None:
            return
        found = sum(1 for e in pl.entries if Path(e.path).is_file())
        missing = len(pl.entries) - found
        info = f"{pl.name}: {len(pl.entries)} tracks"
        if missing:
            info += f" · {missing} no están en su ruta (se buscarán en las carpetas de búsqueda)"
        self.playlist_info.setText(info)
        self.table.setRowCount(len(pl.entries))
        for row, e in enumerate(pl.entries):
            values = [str(row + 1), e.title, Path(e.path).suffix.lstrip(".").upper(), "",
                      Status.PENDING.value, "", "", "", "", "", ""]
            for col, v in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(v))
            self._paint_status(row, Status.PENDING)
        self.progress.setMaximum(len(pl.entries))
        self.progress.setValue(0)
        self.summary.setText("")
        self.start_btn.setEnabled(True)
        self.open_btn.setEnabled(False)
        self.report_btn.setEnabled(False)

    # --- Ajustes -------------------------------------------------------------

    def _pick_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Carpeta de salida", self.output.text())
        if path:
            self.output.setText(path)

    def _add_search_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Carpeta donde buscar tracks")
        if path and path not in self._search_dirs():
            self.search_list.addItem(path)

    def _remove_search_dir(self) -> None:
        for item in self.search_list.selectedItems():
            self.search_list.takeItem(self.search_list.row(item))

    def _update_start_label(self) -> None:
        if self.job is None:
            self.start_btn.setText("Analizar set" if self.analyze_only.isChecked() else "Normalizar set")

    # --- Proceso -------------------------------------------------------------

    def _start_or_cancel(self) -> None:
        if self.job is not None:
            self.job.cancel()
            self.start_btn.setEnabled(False)
            self.start_btn.setText("Cancelando…")
            return
        pl = self._current_playlist()
        if pl is None:
            return
        self._save_prefs()
        settings = Settings(
            target_lufs=self.target.value(),
            ceiling_dbtp=self.ceiling.value(),
            workers=self.workers.value(),
            output_dir=Path(self.output.text()).expanduser(),
            copy_originals=self.copy_originals.isChecked(),
            analyze_only=self.analyze_only.isChecked(),
            search_dirs=[Path(p) for p in self._search_dirs()],
        )
        self._show_playlist(self.playlist_combo.currentIndex())
        self.job = Job(pl, settings, self.bridge.track_updated.emit)
        self.start_btn.setText("Cancelar")
        self.start_btn.setObjectName("")
        self.start_btn.setStyle(self.start_btn.style())
        self._set_inputs_enabled(False)
        threading.Thread(target=self._run_job, daemon=True).start()

    def _run_job(self) -> None:
        try:
            self.job.run()
        except Exception as exc:
            self.bridge.failed.emit(str(exc))
        else:
            self.bridge.finished.emit()

    def _set_inputs_enabled(self, enabled: bool) -> None:
        for w in (self.target, self.ceiling, self.workers, self.output, self.copy_originals,
                  self.analyze_only, self.playlist_combo, self.search_list):
            w.setEnabled(enabled)

    def _paint_status(self, row: int, status: Status) -> None:
        item = self.table.item(row, 4)
        if item is not None:
            item.setForeground(QColor(STATUS_COLORS.get(status, "#c9a227")))

    def _on_track(self, t: Track) -> None:
        row = t.index - 1
        f = lambda v: "" if v is None else f"{v:.1f}"  # noqa: E731
        values = {
            2: (t.source.suffix.lstrip(".").upper() if t.source else None),
            3: t.agent,
            4: t.status.value,
            5: f(t.before.integrated) if t.before else "",
            6: f(t.before.true_peak) if t.before else "",
            7: f"{t.gain_db:+.1f} dB" if t.gain_db is not None else "",
            8: f(t.after.integrated) if t.after else "",
            9: f(t.after.true_peak) if t.after else "",
            10: t.message,
        }
        for col, v in values.items():
            if v is not None:
                self.table.item(row, col).setText(v)
        self._paint_status(row, t.status)
        finished = (Status.DONE, Status.ANALYZED, Status.MISSING, Status.ERROR, Status.CANCELLED)
        self.progress.setValue(sum(1 for x in self.job.tracks if x.status in finished))

    def _on_finished(self) -> None:
        job = self.job
        ok = sum(1 for t in job.tracks if t.status in (Status.DONE, Status.ANALYZED))
        missing = sum(1 for t in job.tracks if t.status == Status.MISSING)
        errors = sum(1 for t in job.tracks if t.status == Status.ERROR)
        parts = [f"{ok} listos"]
        if missing:
            parts.append(f"{missing} no encontrados")
        if errors:
            parts.append(f"{errors} con error")
        self.summary.setText(" · ".join(parts))
        self.last_out = job.out_dir
        self._reset_after_job()

    def _on_failed(self, message: str) -> None:
        QMessageBox.critical(self, "Algo ha fallado", message)
        self._reset_after_job()

    def _reset_after_job(self) -> None:
        self.job = None
        self._set_inputs_enabled(True)
        self.start_btn.setEnabled(True)
        self.start_btn.setObjectName("primary")
        self.start_btn.setStyle(self.start_btn.style())
        self._update_start_label()
        has_out = getattr(self, "last_out", None) is not None
        self.open_btn.setEnabled(has_out)
        self.report_btn.setEnabled(has_out)

    def _open_output(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_out)))

    def _open_report(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_out / "informe.html")))

    def closeEvent(self, event):  # noqa: N802
        if self.job is not None:
            self.job.cancel()
        self._save_prefs()
        super().closeEvent(event)


def _dark_palette() -> QPalette:
    pal = QPalette()
    bg, base, text = QColor("#121214"), QColor("#151518"), QColor("#e8e8ea")
    pal.setColor(QPalette.Window, bg)
    pal.setColor(QPalette.WindowText, text)
    pal.setColor(QPalette.Base, base)
    pal.setColor(QPalette.AlternateBase, QColor("#1b1b1f"))
    pal.setColor(QPalette.Text, text)
    pal.setColor(QPalette.Button, QColor("#26262c"))
    pal.setColor(QPalette.ButtonText, text)
    pal.setColor(QPalette.Highlight, QColor("#3a3320"))
    pal.setColor(QPalette.HighlightedText, text)
    pal.setColor(QPalette.ToolTipBase, QColor("#26262c"))
    pal.setColor(QPalette.ToolTipText, text)
    return pal


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Ultimate LUFS Equalizer")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    app.setPalette(_dark_palette())
    app.setStyleSheet(STYLE)
    font = QFont()
    font.setPointSize(10)
    app.setFont(font)
    win = MainWindow()
    win.show()
    if len(sys.argv) > 1 and Path(sys.argv[1]).exists():
        win._load(sys.argv[1])
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

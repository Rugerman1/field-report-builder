"""PySide6 main window."""

from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile
import traceback

from PySide6.QtCore import QDate, QSize, Qt, QThread, Signal
from PySide6.QtGui import QAction, QActionGroup, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QDateEdit, QDoubleSpinBox, QFileDialog, QFormLayout,
    QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
    QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from .. import __version__, claude, extract, photos as photo_mod, transcribe, weather
from ..model import TEXT_SECTIONS, CrewRow, EquipmentRow, Report, WorkItem
from ..sample import example_report

FILE_FILTER = "Field reports (*.frb.json);;All files (*)"
MEDIA_FILTER = ("Photos and voice memos (*.jpg *.jpeg *.png *.heic *.heif *.webp *.m4a *.mp3 *.wav *.aac "
                "*.ogg *.opus *.flac *.amr *.3gp *.mp4);;All files (*)")
NO_COORD = -999.0


class Worker(QThread):
    """Run `fn(progress)` off the UI thread."""

    progress = Signal(str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn(self.progress.emit))
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"{e}\n\n{traceback.format_exc()}")


class DropList(QListWidget):
    """File list that accepts photos and voice memos dragged from Explorer."""

    dropped = Signal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setMinimumHeight(150)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.dropped.emit(paths)
            e.acceptProposedAction()


def _table(headers, widths=None):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().setVisible(False)
    t.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
    for i, w in enumerate(widths or []):
        if w:
            t.setColumnWidth(i, w)
    t.setMinimumHeight(130)
    return t


def _cell(t, r, c) -> str:
    item = t.item(r, c)
    return item.text().strip() if item else ""


def _num(text, kind=float, default=0):
    try:
        return kind(float(text))
    except ValueError:
        return default


def _coord(spin) -> float | None:
    return None if spin.value() == NO_COORD else spin.value()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Field Report Builder {__version__}")
        self.resize(1320, 860)
        self.report = Report()
        self.path: str | None = None
        self.worker: Worker | None = None
        self.whisper_size = claude.load_settings().get("whisper_model", transcribe.DEFAULT_MODEL)
        self._photo_row = -1
        self._build_menu()
        self._build_ui()
        self.load_report(example_report())
        self.statusBar().showMessage(
            "Example day loaded. Drop in your photos and voice memos, or press Build report to see the example.")

    # ------------------------------------------------------------- layout

    def _build_menu(self):
        m = self.menuBar()
        f = m.addMenu("&File")
        for text, slot, key in (("&New report", self.new_report, "Ctrl+N"), ("&Open report...", self.open_report,
                                "Ctrl+O"), ("&Save report", self.save_report, "Ctrl+S"),
                                ("Save report &as...", self.save_report_as, None), (None, None, None),
                                ("Export &PDF...", self.export_pdf, "Ctrl+P"),
                                ("Export &Word...", self.export_docx, "Ctrl+W"), (None, None, None),
                                ("E&xit", self.close, None)):
            if text is None:
                f.addSeparator()
                continue
            a = QAction(text, self)
            a.triggered.connect(slot)
            if key:
                a.setShortcut(key)
            f.addAction(a)
        s = m.addMenu("&Settings")
        a = QAction("Claude API key...", self)
        a.triggered.connect(self.set_api_key)
        s.addAction(a)
        wm = s.addMenu("Whisper model")
        group = QActionGroup(self)
        for size, label in transcribe.MODEL_SIZES.items():
            a = QAction(label, self, checkable=True)
            a.setChecked(size == self.whisper_size)
            a.triggered.connect(lambda _=False, s_=size: self.set_whisper(s_))
            group.addAction(a)
            wm.addAction(a)
        h = m.addMenu("&Help")
        a = QAction("About", self)
        a.triggered.connect(self.about)
        h.addAction(a)

    def _build_ui(self):
        split = QSplitter()
        split.addWidget(self._left_panel())
        split.addWidget(self._right_panel())
        split.setSizes([400, 920])
        self.setCentralWidget(split)
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(220)
        self.progress.setTextVisible(False)
        self.progress.hide()
        self.statusBar().addPermanentWidget(self.progress)

    def _left_panel(self):
        inner = QWidget()
        v = QVBoxLayout(inner)

        job = QGroupBox("Job")
        form = QFormLayout(job)
        self.project = QLineEdit()
        self.contract_no = QLineEdit()
        self.contractor = QLineEdit()
        self.inspector = QLineEdit()
        self.report_no = QLineEdit()
        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("ddd MMM d, yyyy")
        self.location = QLineEdit()
        self.location.setPlaceholderText("Town, ST")
        find = QPushButton("Find")
        find.setToolTip("Look up the coordinates of this town for the weather")
        find.clicked.connect(self.find_location)
        loc_row = QHBoxLayout()
        loc_row.addWidget(self.location)
        loc_row.addWidget(find)
        self.lat = QDoubleSpinBox()
        self.lon = QDoubleSpinBox()
        for spin, lo, hi in ((self.lat, -90, 90), (self.lon, -180, 180)):
            spin.setRange(NO_COORD, hi)
            spin.setDecimals(4)
            spin.setSpecialValueText("not set")
            spin.setMinimum(NO_COORD)
        coord_row = QHBoxLayout()
        coord_row.addWidget(self.lat)
        coord_row.addWidget(self.lon)
        form.addRow("Project", self.project)
        form.addRow("Contract no.", self.contract_no)
        form.addRow("Prime contractor", self.contractor)
        form.addRow("Inspector", self.inspector)
        form.addRow("Date", self.date)
        form.addRow("Report no.", self.report_no)
        form.addRow("Location", loc_row)
        form.addRow("Lat / long", coord_row)
        v.addWidget(job)

        files = QGroupBox("Photos and voice memos")
        fv = QVBoxLayout(files)
        hint = QLabel("Drag files here from your phone's folder, or use Add.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(mid);")
        fv.addWidget(hint)
        self.files = DropList()
        self.files.dropped.connect(self.add_paths)
        fv.addWidget(self.files)
        row = QHBoxLayout()
        add = QPushButton("Add...")
        add.clicked.connect(self.add_files)
        rem = QPushButton("Remove")
        rem.clicked.connect(self.remove_files)
        row.addWidget(add)
        row.addWidget(rem)
        fv.addLayout(row)
        v.addWidget(files)

        steps = QGroupBox("Build")
        grid = QGridLayout(steps)
        self.step_buttons = []
        for i, (text, slot) in enumerate((("1. Transcribe memos", self.do_transcribe),
                                          ("2. Fill report from notes", self.do_fill),
                                          ("3. Get weather", self.do_weather),
                                          ("4. Caption photos", self.do_captions))):
            b = QPushButton(text)
            b.clicked.connect(slot)
            grid.addWidget(b, i // 2, i % 2)
            self.step_buttons.append(b)
        self.build_all = QPushButton("Build report (all steps)")
        self.build_all.setStyleSheet("font-weight: bold; padding: 6px;")
        self.build_all.clicked.connect(self.do_all)
        grid.addWidget(self.build_all, 2, 0, 1, 2)
        exp = QHBoxLayout()
        pdf = QPushButton("Export PDF")
        pdf.clicked.connect(self.export_pdf)
        doc = QPushButton("Export Word")
        doc.clicked.connect(self.export_docx)
        exp.addWidget(pdf)
        exp.addWidget(doc)
        grid.addLayout(exp, 3, 0, 1, 2)
        self.step_buttons += [self.build_all, pdf, doc]
        v.addWidget(steps)
        self.ai_label = QLabel()
        self.ai_label.setWordWrap(True)
        self.ai_label.setStyleSheet("color: palette(mid);")
        v.addWidget(self.ai_label)
        v.addStretch(1)
        self._update_ai_label()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        scroll.setMinimumWidth(360)
        return scroll

    def _right_panel(self):
        self.tabs = QTabWidget()

        notes = QWidget()
        nv = QVBoxLayout(notes)
        lab = QLabel("Your notes for the day. Transcribed memos land here; you can also type or paste notes, "
                     "then press Fill report from notes.")
        lab.setWordWrap(True)
        nv.addWidget(lab)
        self.transcript = QPlainTextEdit()
        nv.addWidget(self.transcript)
        self.tabs.addTab(notes, "Notes")

        rep = QWidget()
        rv = QVBoxLayout(rep)
        wbox = QGroupBox("Weather")
        wg = QGridLayout(wbox)
        self.w_am, self.w_pm = QLineEdit(), QLineEdit()
        self.w_hi, self.w_lo, self.w_7, self.w_12, self.w_16, self.w_rain, self.w_wind = (
            QLineEdit() for _ in range(7))
        self.w_observed = QLineEdit()
        cells = (("AM", self.w_am), ("PM", self.w_pm), ("High F", self.w_hi), ("Low F", self.w_lo),
                 ("7 AM F", self.w_7), ("Noon F", self.w_12), ("4 PM F", self.w_16), ("Precip in", self.w_rain),
                 ("Wind mph", self.w_wind))
        for i, (label, w) in enumerate(cells):
            wg.addWidget(QLabel(label), (i // 5) * 2, i % 5)
            wg.addWidget(w, (i // 5) * 2 + 1, i % 5)
        wg.addWidget(QLabel("On site"), 4, 0)
        wg.addWidget(self.w_observed, 4, 1, 1, 4)
        rv.addWidget(wbox)

        self.crews = _table(["Contractor", "Classification", "No.", "Hours"], [0, 170, 60, 70])
        self.equipment = _table(["Description", "No.", "Status", "Hours"], [0, 60, 110, 70])
        self.work = _table(["Description", "Location", "Quantity"], [0, 170, 130])
        for title, table in (("Contractor forces", self.crews), ("Equipment", self.equipment),
                             ("Work performed", self.work)):
            rv.addWidget(self._table_box(title, table))

        self.lists: dict[str, QPlainTextEdit] = {}
        grid = QGridLayout()
        for i, (key, title) in enumerate(TEXT_SECTIONS + [("remarks", "Remarks")]):
            box = QGroupBox(title + ("" if key == "remarks" else " (one per line)"))
            bl = QVBoxLayout(box)
            ed = QPlainTextEdit()
            ed.setMinimumHeight(80)
            bl.addWidget(ed)
            self.lists[key] = ed
            grid.addWidget(box, i // 2, i % 2)
        rv.addLayout(grid)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(rep)
        self.tabs.addTab(scroll, "Report")

        ph = QWidget()
        pl = QHBoxLayout(ph)
        self.photo_list = QListWidget()
        self.photo_list.setViewMode(QListWidget.IconMode)
        self.photo_list.setIconSize(QSize(160, 120))
        self.photo_list.setResizeMode(QListWidget.Adjust)
        self.photo_list.setSpacing(6)
        self.photo_list.currentRowChanged.connect(self._photo_selected)
        pl.addWidget(self.photo_list, 3)
        side = QVBoxLayout()
        self.photo_preview = QLabel("Select a photo")
        self.photo_preview.setAlignment(Qt.AlignCenter)
        self.photo_preview.setMinimumSize(360, 270)
        self.photo_info = QLabel()
        self.photo_info.setWordWrap(True)
        self.photo_caption = QPlainTextEdit()
        self.photo_caption.setPlaceholderText("Caption")
        self.photo_caption.setMaximumHeight(90)
        self.photo_include = QCheckBox("Include in report")
        side.addWidget(self.photo_preview)
        side.addWidget(self.photo_info)
        side.addWidget(QLabel("Caption"))
        side.addWidget(self.photo_caption)
        side.addWidget(self.photo_include)
        side.addStretch(1)
        pl.addLayout(side, 2)
        self.tabs.addTab(ph, "Photos")
        return self.tabs

    def _table_box(self, title, table):
        box = QGroupBox(title)
        v = QVBoxLayout(box)
        v.addWidget(table)
        row = QHBoxLayout()
        add = QPushButton("Add row")
        add.clicked.connect(lambda: table.insertRow(table.rowCount()))
        rem = QPushButton("Remove row")
        rem.clicked.connect(lambda: table.removeRow(table.currentRow()) if table.currentRow() >= 0 else None)
        row.addWidget(add)
        row.addWidget(rem)
        row.addStretch(1)
        v.addLayout(row)
        return box

    # -------------------------------------------------- report <-> widgets

    def load_report(self, r: Report):
        self.report = r
        self.project.setText(r.project)
        self.contract_no.setText(r.contract_no)
        self.contractor.setText(r.contractor)
        self.inspector.setText(r.inspector)
        self.report_no.setText(r.report_no)
        self.location.setText(r.location)
        self.date.setDate(QDate(r.date.year, r.date.month, r.date.day))
        self.lat.setValue(NO_COORD if r.latitude is None else r.latitude)
        self.lon.setValue(NO_COORD if r.longitude is None else r.longitude)
        self.transcript.setPlainText(r.transcript)
        self._show_fields()
        self._refresh_files()

    def _show_fields(self):
        r, w = self.report, self.report.weather

        def f(v, fmt="{:.0f}"):
            return "" if v is None else fmt.format(v)

        self.w_am.setText(w.conditions_am)
        self.w_pm.setText(w.conditions_pm)
        for edit, v, fmt in ((self.w_hi, w.temp_high_f, "{:.0f}"), (self.w_lo, w.temp_low_f, "{:.0f}"),
                             (self.w_7, w.temp_7am_f, "{:.0f}"), (self.w_12, w.temp_noon_f, "{:.0f}"),
                             (self.w_16, w.temp_4pm_f, "{:.0f}"), (self.w_rain, w.precip_in, "{:.2f}"),
                             (self.w_wind, w.wind_max_mph, "{:.0f}")):
            edit.setText(f(v, fmt))
        self.w_observed.setText(w.observed)
        self._fill(self.crews, [[c.contractor, c.trade, str(c.count), f"{c.hours:g}" if c.hours else ""]
                                for c in r.crews])
        self._fill(self.equipment, [[e.description, str(e.count), e.status, f"{e.hours:g}" if e.hours else ""]
                                    for e in r.equipment])
        self._fill(self.work, [[x.description, x.location, x.quantity] for x in r.work])
        for key, _ in TEXT_SECTIONS:
            self.lists[key].setPlainText("\n".join(getattr(r, key)))
        self.lists["remarks"].setPlainText(r.remarks)

    @staticmethod
    def _fill(table, rows):
        table.setRowCount(0)
        for row in rows:
            i = table.rowCount()
            table.insertRow(i)
            for j, v in enumerate(row):
                table.setItem(i, j, QTableWidgetItem(v))
        table.resizeRowsToContents()

    def collect(self) -> Report:
        """Read every widget back into self.report."""
        self._save_photo_edits()
        r = self.report
        r.project = self.project.text().strip()
        r.contract_no = self.contract_no.text().strip()
        r.contractor = self.contractor.text().strip()
        r.inspector = self.inspector.text().strip()
        r.report_no = self.report_no.text().strip()
        r.location = self.location.text().strip()
        r.report_date = self.date.date().toPython().isoformat()
        r.latitude, r.longitude = _coord(self.lat), _coord(self.lon)
        r.transcript = self.transcript.toPlainText().strip()
        w = r.weather
        w.conditions_am = self.w_am.text().strip()
        w.conditions_pm = self.w_pm.text().strip()

        def opt(edit):
            t = edit.text().strip()
            return _num(t, float, None) if t else None

        w.temp_high_f, w.temp_low_f = opt(self.w_hi), opt(self.w_lo)
        w.temp_7am_f, w.temp_noon_f, w.temp_4pm_f = opt(self.w_7), opt(self.w_12), opt(self.w_16)
        w.precip_in, w.wind_max_mph = opt(self.w_rain), opt(self.w_wind)
        w.observed = self.w_observed.text().strip()
        t = self.crews
        r.crews = [CrewRow(_cell(t, i, 0), _cell(t, i, 1), _num(_cell(t, i, 2), int), _num(_cell(t, i, 3)))
                   for i in range(t.rowCount()) if _cell(t, i, 0) or _cell(t, i, 1)]
        t = self.equipment
        r.equipment = [EquipmentRow(_cell(t, i, 0), _num(_cell(t, i, 1), int, 1), _cell(t, i, 2) or "Working",
                                    _num(_cell(t, i, 3))) for i in range(t.rowCount()) if _cell(t, i, 0)]
        t = self.work
        r.work = [WorkItem(_cell(t, i, 0), _cell(t, i, 1), _cell(t, i, 2)) for i in range(t.rowCount())
                  if _cell(t, i, 0)]
        for key, _ in TEXT_SECTIONS:
            setattr(r, key, [x.strip() for x in self.lists[key].toPlainText().splitlines() if x.strip()])
        r.remarks = self.lists["remarks"].toPlainText().strip()
        return r

    # ---------------------------------------------------------------- files

    def add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Add photos and voice memos", "", MEDIA_FILTER)
        if paths:
            self.add_paths(paths)

    def add_paths(self, paths: list[str]):
        self.collect()
        r = self.report
        expanded = []
        for p in paths:
            if os.path.isdir(p):
                expanded += [os.path.join(p, f) for f in sorted(os.listdir(p))]
            else:
                expanded.append(p)
        have = {p.path for p in r.photos} | set(r.memos)
        new_photos, skipped = [], 0
        for p in expanded:
            if p in have:
                continue
            if photo_mod.is_photo(p):
                new_photos.append(photo_mod.read_photo(p))
            elif photo_mod.is_audio(p):
                r.memos.append(p)
            else:
                skipped += 1
        r.photos = photo_mod.sort_by_time(r.photos + new_photos)
        notes = []
        located = [p for p in new_photos if p.latitude is not None]
        if located and r.latitude is None:
            r.latitude, r.longitude = located[0].latitude, located[0].longitude
            self.lat.setValue(r.latitude)
            self.lon.setValue(r.longitude)
            notes.append("site location set from photo GPS")
        days = sorted({p.taken[:10] for p in new_photos if p.taken})
        if len(days) == 1 and days[0] != r.report_date:
            d = dt.date.fromisoformat(days[0])
            self.date.setDate(QDate(d.year, d.month, d.day))
            notes.append(f"date set to {d:%b %d} from the photos")
        msg = f"Added {len(new_photos)} photo(s) and {len(r.memos)} memo(s) total"
        if skipped:
            msg += f", skipped {skipped} file(s) that are not photos or audio"
        self._refresh_files()
        self.statusBar().showMessage(msg + ("; " + ", ".join(notes) if notes else "") + ".")

    def remove_files(self):
        self.collect()
        gone = {i.data(Qt.UserRole) for i in self.files.selectedItems()}
        self.report.memos = [m for m in self.report.memos if m not in gone]
        self.report.photos = [p for p in self.report.photos if p.path not in gone]
        self._refresh_files()

    def _refresh_files(self):
        self.files.clear()
        for m in self.report.memos:
            it = QListWidgetItem("Memo: " + os.path.basename(m))
            it.setData(Qt.UserRole, m)
            self.files.addItem(it)
        for p in self.report.photos:
            it = QListWidgetItem(f"Photo: {os.path.basename(p.path)}  {photo_mod.taken_label(p)}")
            it.setData(Qt.UserRole, p.path)
            self.files.addItem(it)
        self._photo_row = -1
        self.photo_list.clear()
        for p in self.report.photos:
            it = QListWidgetItem(os.path.basename(p.path))
            pix = self._pixmap(p.path, 160)
            if pix is not None:
                it.setIcon(QIcon(pix))
            self.photo_list.addItem(it)
        self.tabs.setTabText(2, f"Photos ({len(self.report.photos)})")

    @staticmethod
    def _pixmap(path, size):
        try:
            data = photo_mod.jpeg_bytes(path, max_px=size, quality=80)
        except OSError:
            return None
        pix = QPixmap()
        pix.loadFromData(data, "JPG")
        return pix

    def _photo_selected(self, row):
        self._save_photo_edits()
        self._photo_row = row
        if row < 0 or row >= len(self.report.photos):
            return
        p = self.report.photos[row]
        pix = self._pixmap(p.path, 720)
        if pix is not None:
            self.photo_preview.setPixmap(pix.scaled(self.photo_preview.width(), 360, Qt.KeepAspectRatio,
                                                    Qt.SmoothTransformation))
        info = [os.path.basename(p.path)]
        if p.taken:
            info.append("Taken " + dt.datetime.fromisoformat(p.taken).strftime("%b %d %Y, %I:%M %p"))
        if p.latitude is not None:
            info.append(f"GPS {p.latitude:.5f}, {p.longitude:.5f}")
        self.photo_info.setText("\n".join(info))
        self.photo_caption.setPlainText(p.caption)
        self.photo_include.setChecked(p.include)

    def _save_photo_edits(self):
        row = self._photo_row
        if 0 <= row < len(self.report.photos):
            p = self.report.photos[row]
            p.caption = self.photo_caption.toPlainText().strip()
            p.include = self.photo_include.isChecked()

    # ---------------------------------------------------------------- steps

    def _run(self, label, fn, on_done):
        if self.worker is not None and self.worker.isRunning():
            return
        self.collect()
        for b in self.step_buttons:
            b.setEnabled(False)
        self.progress.setRange(0, 0)
        self.progress.show()
        self.statusBar().showMessage(label + "...")
        self.worker = Worker(fn)
        self.worker.progress.connect(lambda m: self.statusBar().showMessage(m))
        self.worker.done.connect(lambda res: (self._finish(), on_done(res)))
        self.worker.failed.connect(lambda err: (self._finish(), self._error(label, err)))
        self.worker.start()

    def _finish(self):
        for b in self.step_buttons:
            b.setEnabled(True)
        self.progress.hide()

    def _error(self, label, err):
        self.statusBar().showMessage(f"{label} failed.")
        QMessageBox.warning(self, "Field Report Builder", f"{label} failed:\n\n{err.split(chr(10))[0]}")

    def _transcribe_all(self, progress) -> str:
        memos = self.report.memos
        if not memos:
            return ""
        if not transcribe.available():
            raise RuntimeError("Speech-to-text is not installed in this build.")
        texts = []
        for i, m in enumerate(memos, 1):
            progress(f"Transcribing memo {i} of {len(memos)} ({os.path.basename(m)}). The first run downloads "
                     f"the Whisper model.")
            t = transcribe.transcribe(m, self.whisper_size)
            progress(f"Memo {i}: {t.audio_seconds:.0f} s of audio in {t.seconds_taken:.0f} s")
            texts.append(t.text)
        return "\n\n".join(texts)

    def do_transcribe(self):
        if not self.report.memos:
            self.statusBar().showMessage("No voice memos added. Drop .m4a, .mp3 or .wav files on the list.")
            return
        self._run("Transcribing", self._transcribe_all, self._got_transcript)

    def _got_transcript(self, text):
        if text:
            self.transcript.setPlainText(text)
            self.report.transcript = text
            self.tabs.setCurrentIndex(0)
        self.statusBar().showMessage(f"Transcribed {len(self.report.memos)} memo(s) on this computer.")

    def do_fill(self):
        if not self.transcript.toPlainText().strip():
            self.statusBar().showMessage("No notes yet. Transcribe memos or type notes on the Notes tab.")
            return
        self._run("Filling the report", lambda _p: extract.fill_report(self.report), self._filled)

    def _filled(self, source):
        self._show_fields()
        self.tabs.setCurrentIndex(1)
        how = "Claude" if source == "claude" else "the offline sorter"
        self.statusBar().showMessage(f"Report filled from your notes by {how}. Check every line before you sign.")

    def _weather(self, _progress):
        r = self.report
        if r.latitude is None or r.longitude is None:
            raise RuntimeError("Set the site location first (type a town and press Find, or add a GPS photo).")
        w = weather.fetch_weather(r.latitude, r.longitude, r.date)
        w.observed = r.weather.observed
        return w

    def do_weather(self):
        self._run("Getting weather", self._weather, self._got_weather)

    def _got_weather(self, w):
        self.report.weather = w
        self._show_fields()
        self.statusBar().showMessage(f"Weather for {self.report.report_date}: {w.summary()}.")

    def do_captions(self):
        if not self.report.photos:
            self.statusBar().showMessage("No photos added.")
            return
        self._run("Captioning photos",
                  lambda p: photo_mod.caption_photos(self.report.photos, self.report.transcript, progress=p),
                  self._captioned)

    def _captioned(self, source):
        self._refresh_files()
        self.statusBar().showMessage(f"Captions written ({source}). Edit any of them on the Photos tab.")

    def _all(self, progress):
        r = self.report
        done = []
        if r.memos:
            text = self._transcribe_all(progress)
            if text:
                r.transcript = text
                done.append("transcribed")
        if r.transcript:
            progress("Filling the report from your notes")
            done.append("filled by " + ("Claude" if extract.fill_report(r) == "claude" else "the offline sorter"))
        if r.latitude is not None and r.longitude is not None:
            progress("Getting weather")
            try:
                obs = r.weather.observed
                r.weather = weather.fetch_weather(r.latitude, r.longitude, r.date)
                r.weather.observed = obs
                done.append("weather added")
            except weather.WeatherError as e:
                done.append(f"weather skipped ({e})")
        if r.photos:
            photo_mod.caption_photos(r.photos, r.transcript, progress=progress)
            done.append("photos captioned")
        return done

    def do_all(self):
        self._run("Building the report", self._all, self._built)

    def _built(self, done):
        self.transcript.setPlainText(self.report.transcript)
        self._show_fields()
        self._refresh_files()
        self.tabs.setCurrentIndex(1)
        self.statusBar().showMessage("Report built: " + ", ".join(done) + ". Review it, then export.")

    def find_location(self):
        place = self.location.text().strip()
        if not place:
            return
        try:
            lat, lon, label = weather.geocode(place)
        except weather.WeatherError as e:
            QMessageBox.warning(self, "Field Report Builder", str(e))
            return
        self.lat.setValue(lat)
        self.lon.setValue(lon)
        self.statusBar().showMessage(f"Found {label}.")

    # --------------------------------------------------------- save/export

    def new_report(self):
        r = Report(inspector=self.inspector.text().strip())
        self.path = None
        self.load_report(r)

    def open_report(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open report", "", FILE_FILTER)
        if path:
            self.load_report(Report.load(path))
            self.path = path

    def save_report(self):
        if not self.path:
            return self.save_report_as()
        self.collect().save(self.path)
        self.statusBar().showMessage(f"Saved {self.path}")

    def save_report_as(self):
        name = f"daily-report-{self.date.date().toPython().isoformat()}.frb.json"
        path, _ = QFileDialog.getSaveFileName(self, "Save report", name, FILE_FILTER)
        if path:
            self.path = path
            self.save_report()

    def _export(self, kind):
        r = self.collect()
        ext = "pdf" if kind == "PDF" else "docx"
        name = f"daily-report-{r.report_date}.{ext}"
        path, _ = QFileDialog.getSaveFileName(self, f"Export {kind}", name, f"{kind} (*.{ext})")
        if path:
            self.write(path)

    def write(self, path):
        from ..report_docx import build_docx
        from ..report_pdf import build_pdf

        r = self.collect()
        (build_pdf if path.lower().endswith(".pdf") else build_docx)(r, path)
        self.statusBar().showMessage(f"Exported {path}")

    def export_pdf(self):
        self._export("PDF")

    def export_docx(self):
        self._export("Word")

    # ------------------------------------------------------------- settings

    def set_api_key(self):
        key, ok = QInputDialog.getText(self, "Claude API key",
                                       "Paste your Anthropic API key. It is saved in %APPDATA%\\FieldReportBuilder\n"
                                       "and used to sort your notes and caption photos. Leave blank to stay offline.",
                                       QLineEdit.Password, claude.api_key() or "")
        if ok:
            claude.save_api_key(key)
            self._update_ai_label()

    def set_whisper(self, size):
        self.whisper_size = size
        claude.save_setting("whisper_model", size)

    def _update_ai_label(self):
        if claude.api_key():
            self.ai_label.setText("Claude is on: notes are sorted and photos captioned by Claude. Voice memos are "
                                  "always transcribed on this computer.")
        else:
            self.ai_label.setText("Offline mode: notes are sorted by built-in rules and photos get plain captions. "
                                  "Add a Claude API key in Settings for smarter sorting and real captions.")

    def about(self):
        QMessageBox.about(self, "Field Report Builder",
                          f"Field Report Builder {__version__}\n\nTurns site photos and voice memos into an "
                          "inspector's daily work report.\n\nSpeech-to-text: faster-whisper (offline)\n"
                          "Weather: Open-Meteo\nSorting and captions: Claude (optional)\n\n"
                          "Student-built tool. Check every report before you sign it.")


# ------------------------------------------------------------------ entry


def selftest() -> int:
    """Build the window, run the offline steps on the example, export both formats."""
    from ..sample import make_sample_photos

    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    out = tempfile.mkdtemp(prefix="frb-selftest-")
    win.add_paths(make_sample_photos(os.path.join(out, "photos")))
    win.collect()
    assert extract.fill_report(win.report, use_claude=False) == "offline"
    win._show_fields()
    assert win.crews.rowCount() == 4 and win.work.rowCount() == 2
    photo_mod.caption_photos(win.report.photos, win.report.transcript)
    win._refresh_files()
    for name in ("selftest.pdf", "selftest.docx"):
        path = os.path.join(out, name)
        win.write(path)
        assert os.path.getsize(path) > 10_000, path
    import ctranslate2  # noqa: F401  (bundled speech-to-text engine)
    import faster_whisper  # noqa: F401
    app.processEvents()
    win.close()
    return 0


def transcribe_cli(audio: str, out: str, size: str) -> int:
    t = transcribe.transcribe(audio, size)
    with open(out, "w", encoding="utf-8") as f:
        f.write(t.text + "\n")
        f.write(f"# {t.audio_seconds:.1f} s audio, {t.seconds_taken:.1f} s, model {t.model}\n")
    return 0


def main():
    args = sys.argv[1:]
    if "--selftest" in args:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        sys.exit(selftest())
    if "--transcribe" in args:
        i = args.index("--transcribe")
        size = args[args.index("--model") + 1] if "--model" in args else transcribe.DEFAULT_MODEL
        sys.exit(transcribe_cli(args[i + 1], args[i + 2], size))
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Field Report Builder")
    win = MainWindow()
    win.show()
    if args and args[0].endswith(".frb.json"):
        win.load_report(Report.load(args[0]))
        win.path = args[0]
    sys.exit(app.exec())

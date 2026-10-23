import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_window_builds_a_report_and_exports(tmp_path):
    from PySide6.QtWidgets import QApplication

    from field_report_builder import extract
    from field_report_builder.sample import make_sample_photos
    from field_report_builder.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    win.add_paths(make_sample_photos(str(tmp_path / "photos")) + [str(tmp_path / "memo.m4a"),
                                                                  str(tmp_path / "readme.txt")])
    assert len(win.report.photos) == 2 and len(win.report.memos) == 1
    assert win.photo_list.count() == 2
    win.collect()
    extract.fill_report(win.report, use_claude=False)
    win._show_fields()
    assert win.crews.rowCount() == 4
    win.crews.item(0, 2).setText("2")  # inspector corrects a count by hand
    win.photo_list.setCurrentRow(1)
    win.photo_caption.setPlainText("Curb pour, east side.")
    win.photo_list.setCurrentRow(0)
    r = win.collect()
    assert r.crews[0].count == 2
    assert r.photos[1].caption == "Curb pour, east side."
    win.write(str(tmp_path / "out.pdf"))
    win.write(str(tmp_path / "out.docx"))
    assert (tmp_path / "out.pdf").stat().st_size > 10_000
    app.processEvents()

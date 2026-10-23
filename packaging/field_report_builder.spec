# PyInstaller spec: one-folder build (FieldReportBuilder\FieldReportBuilder.exe plus its libraries).
# One-folder because the speech-to-text engine makes a single-file exe slow to start.
# Run from the repo root:  pyinstaller packaging/field_report_builder.spec
import os

from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

datas, binaries, hiddenimports = [], [], ["field_report_builder.ui.main_window"]
# faster-whisper ships the Silero VAD model as package data; ctranslate2 and
# onnxruntime ship native DLLs.  collect_all picks up all three.
for pkg in ("faster_whisper", "ctranslate2", "onnxruntime", "pillow_heif"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    [os.path.join(ROOT, "field_report_builder", "__main__.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "torch", "tensorflow", "PySide6.QtWebEngineCore",
              "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtQuick",
              "PySide6.QtQml", "PySide6.QtCharts", "PySide6.QtPdf"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FieldReportBuilder",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="FieldReportBuilder")

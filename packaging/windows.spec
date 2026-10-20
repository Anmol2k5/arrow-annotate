# Build from the repository root: python -m PyInstaller --clean --noconfirm packaging/windows.spec
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, copy_metadata

root = Path(SPECPATH).parent
resources = root / "build" / "windows" / "resources"
icon = root / "arrow" / "ui" / "assets" / "arrow.ico"
datas = [
    (str(root / "browser_extension"), "browser_extension"),
    (str(root / "arrow" / "ui" / "assets"), "arrow/ui/assets"),
    (str(resources / "THIRD-PARTY-NOTICES"), "THIRD-PARTY-NOTICES"),
]
datas += copy_metadata("arrow-annotate")
binaries = []
hiddenimports = []
# Dynamic backends, COM support, PortAudio, ONNX DLLs and offline OCR models.
for package in (
    "speech_recognition", "pyaudio", "keyboard", "uiautomation",
    "comtypes", "onnxruntime", "rapidocr_onnxruntime",
):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports
datas += collect_data_files("PyQt6", includes=["**/LICENSE*", "**/COPYING*", "**/licenses/**"])
a = Analysis(
    [str(root / "main.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
common = dict(
    exclude_binaries=True, debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, icon=str(icon), version=str(resources / "version-info.txt"),
    contents_directory="_internal",
)
gui = EXE(pyz, a.scripts, [], name="ArrowAnnotate", console=False, **common)
mcp = EXE(pyz, a.scripts, [], name="ArrowMCP", console=True, **common)
coll = COLLECT(gui, mcp, a.binaries, a.datas, strip=False, upx=False, name="ArrowAnnotate")

from pathlib import Path
import shutil

root = Path(SPECPATH).parent
a = Analysis(
    [str(root / "main.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(root / "config"), "config"),
           (str(root / "assets"), "assets"),
           (str(root / "app" / "ui" / "style.qss"), "app/ui")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Qingyu",
          debug=False, bootloader_ignore_signals=False, strip=False,
          upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Qingyu")
shutil.copyfile(root / "packaging" / "使用说明.md", Path(DISTPATH) / "Qingyu" / "使用说明.md")

from pathlib import Path

root = Path(SPECPATH).parent
a = Analysis(
    [str(root / "main.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(root / "config" / "default_settings.json"), "config"),
           (str(root / "config" / "character.json"), "config"),
           (str(root / "config" / "system_prompt.txt"), "config"),
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
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="Qingyu-Flash",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)

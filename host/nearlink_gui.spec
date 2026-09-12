# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for NearLink GUI — slim build without torch."""

from pathlib import Path

gui_dir = Path(SPECPATH).resolve()

block_cipher = None

mpl_datas = []
try:
    import matplotlib
    mpl_datas.append((str(Path(matplotlib.get_data_path())), "matplotlib/mpl-data"))
except Exception:
    pass

a = Analysis(
    [str(gui_dir / "run_gui.py")],
    pathex=[str(gui_dir)],
    binaries=[],
    datas=[
        *([(str(gui_dir / "anchor_layout.ini"), ".")]
          if (gui_dir / "anchor_layout.ini").exists() else []),
        *mpl_datas,
    ],
    hiddenimports=[
        "PyQt5.sip",
        "matplotlib.backends.backend_qt5agg",
        "numpy.core._methods",
        "numpy.lib.format",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "IPython", "jupyter", "pytest", "torch", "torch.nn"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NearLink_GUI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="NearLink_GUI_Slim",
)

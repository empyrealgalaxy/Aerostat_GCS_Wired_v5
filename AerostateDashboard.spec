# -*- mode: python ; coding: utf-8 -*-
# Build (from this folder):  .\venv\Scripts\pyinstaller.exe AerostateDashboard.spec --noconfirm
# Output:  dist\AerostateDashboard\AerostateDashboard.exe  (use the whole dist\AerostateDashboard folder)

import glob
import os
import tempfile

# Avoid Ultralytics Windows Roaming path collision during PyInstaller's import analysis
_yolo_cfg = os.path.join(tempfile.gettempdir(), "Ultralytics_PyInstaller_Build")
os.environ["YOLO_CONFIG_DIR"] = _yolo_cfg
try:
    os.makedirs(_yolo_cfg, exist_ok=True)
except OSError:
    pass

# Resolve project root (directory that contains run_dashboard.py)
if "SPECPATH" in globals():
    _spec_dir = os.path.dirname(os.path.abspath(SPECPATH))
else:
    _spec_dir = os.getcwd()
if not os.path.isfile(os.path.join(_spec_dir, "run_dashboard.py")):
    _spec_dir = os.getcwd()
if not os.path.isfile(os.path.join(_spec_dir, "run_dashboard.py")):
    raise RuntimeError(
        "Cannot find run_dashboard.py. Run PyInstaller from the 'Aerostate Project' folder "
        "that contains run_dashboard.py and this .spec file."
    )

_pt_datas = [
    (os.path.normpath(p), ".")
    for p in glob.glob(os.path.join(_spec_dir, "*.pt"))
]

_hidden = [
        "paho.mqtt.client",
        "paho.mqtt",
        "fastapi",
        "uvicorn",
        "uvicorn.lifespan",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.http.httptools_impl",
        "uvicorn.protocols.websockets.websockets_impl",
        "uvicorn.loops.auto",
        "uvicorn.loops.uvloop",
        "uvicorn.loops.asyncio",
        "uvicorn.logging",
        "uvicorn.config",
        "uvicorn.server",
        "uvicorn.main",
        "jinja2",
        "jinja2.loaders",
        "websockets",
        "websockets.server",
        "websockets.client",
        "websockets.protocol",
        "starlette.staticfiles",
        "starlette.responses",
        "starlette.applications",
        "starlette.middleware",
        "starlette.routing",
        "starlette.templating",
        "starlette.websockets",
        "pydantic",
        "pydantic.fields",
        "pydantic.main",
        "email_validator",
        "typing_extensions",
        "yarl",
        "multidict",
        "anyio",
        "sniffio",
        "idna",
        "h11",
        "httptools",
        "click",
        "watchfiles",
        "asyncio",
        "ssl",
        "socket",
        "json",
        "csv",
        "logging",
        "logging.handlers",
        "threading",
        "io",
        "traceback",
        "cv2",
        "numpy",
        "PIL",
        "PIL.Image",
        "yaml",
        "torch",
        "torchvision",
        "imageio_ffmpeg",
        "yt_dlp",
        "stream_capture",
        "yolo_detector",
        "intrusion_detector",
        "gimbal_control",
        "psutil",
        "passlib",
        "passlib.handlers",
        "passlib.handlers.bcrypt",
        "cryptography",
        "jose",
        "jose.jwt",
        "ultralytics",
        "ultralytics.nn",
        "ultralytics.nn.tasks",
        "ultralytics.engine",
        "ultralytics.engine.model",
        "ultralytics.engine.predictor",
        "ultralytics.engine.results",
        "ultralytics.utils",
        "ultralytics.utils.ops",
        "ultralytics.trackers",
        "multipart",
        "serial",
        "serial.tools",
        "serial.tools.list_ports",
]
try:
    from PyInstaller.utils.hooks import collect_submodules

    _hidden.extend(collect_submodules("yt_dlp"))
except Exception:
    pass

a = Analysis(
    [os.path.join(_spec_dir, "run_dashboard.py")],
    pathex=[_spec_dir],
    binaries=[],
    datas=[
        (os.path.join(_spec_dir, "templates"), "templates"),
        (os.path.join(_spec_dir, "static"), "static"),
    ]
    + _pt_datas,
    hiddenimports=_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib.tests",
        "numpy.tests",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AerostateDashboard",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AerostateDashboard",
)

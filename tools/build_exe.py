#!/usr/bin/env python3
"""打包 Windows 版。默认打成**单文件 exe**，用户拿到的就是一个 .exe。

    python tools/fetch_model.py
    python tools/build_exe.py              # 跟唱助手（单文件，内置《紫荆花盛开》）
    python tools/build_exe.py separate     # 伴奏分离器（单文件）
    python tools/build_exe.py onedir       # 调试用：目录版，启动快

产物在 dist/ 下。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

APP_NAME = "跟唱助手"
SEP_NAME = "伴奏分离器"


def build(target="app", onedir=False):
    if target == "app" and not common.model_path():
        raise SystemExit("缺少模型，先运行: python tools/fetch_model.py")

    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()

    name = SEP_NAME if target == "separate" else APP_NAME
    entry = os.path.join(common.APP, "separate.py" if target == "separate" else "entry.py")
    icon = os.path.join(common.UI, "app.ico")
    work = os.path.join(common.BUILD, name)

    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)
    os.makedirs(common.DIST, exist_ok=True)

    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onedir" if onedir else "--onefile",
        "--name", name,
        "--icon", icon,
        "--noconsole",
        "--add-data", "%s;ui" % common.UI,
        "--add-data", "%s;models" % common.MODELS,
        "--add-data", "%s;engine" % common.ENGINE,
        "--add-data", "%s;_ffmpeg" % ff,
        "--collect-submodules", "onnxruntime",
        "--hidden-import", "numpy",
        "--hidden-import", "soundfile",
        "--hidden-import", "imageio_ffmpeg",
        "--hidden-import", "tkinter",
        "--hidden-import", "tkinter.messagebox",
        "--hidden-import", "tkinter.filedialog",
        "--collect-submodules", "soundfile",
        "--distpath", common.DIST,
        "--workpath", work,
        "--specpath", work,
    ]
    if target == "app":
        seed = os.path.join(common.APP, "seed")
        if os.path.isdir(seed):
            args += ["--add-data", "%s;seed" % seed]
    for m in ("torch", "torchaudio", "matplotlib", "librosa", "scipy", "pandas",
              "PyQt5", "PySide2", "IPython", "pytest", "PIL", "webview",
              "faster_whisper", "ctranslate2", "av", "numpy.f2py"):
        args += ["--exclude-module", m]
    args.append(entry)

    print("=== 打包 %s ===" % name)
    if subprocess.run(args, cwd=common.ROOT).returncode != 0:
        raise SystemExit("PyInstaller 失败")

    out = os.path.join(common.DIST, name + ".exe")
    if os.path.isfile(out):
        print("完成: %s  (%.0f MB)" % (out, os.path.getsize(out) / 1e6))
    else:
        d = os.path.join(common.DIST, name)
        total = sum(os.path.getsize(os.path.join(b, f)) for b, _, fs in os.walk(d) for f in fs)
        print("完成: %s  (%.0f MB)" % (d, total / 1e6))


def main():
    argv = [a.lower() for a in sys.argv[1:]]
    onedir = "onedir" in argv
    target = "separate" if "separate" in argv else "app"
    build(target, onedir)


if __name__ == "__main__":
    main()

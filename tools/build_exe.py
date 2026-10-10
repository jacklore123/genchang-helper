#!/usr/bin/env python3
"""打包 Windows 版（PyInstaller）。

    python tools/fetch_model.py            # 先拿模型
    python tools/build_exe.py              # onedir，启动快（推荐）
    python tools/build_exe.py onefile      # 单文件，启动稍慢

产物：dist/跟唱助手/跟唱助手.exe（整个目录可拷贝到别的电脑直接用）
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

NAME = "跟唱助手"


def main():
    mode = "--onefile" if "onefile" in sys.argv else "--onedir"
    if not common.model_path():
        raise SystemExit("缺少模型，先运行: python tools/fetch_model.py")

    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    print("ffmpeg:", ff)

    for d in (common.DIST, common.BUILD):
        shutil.rmtree(d, ignore_errors=True)
    os.makedirs(common.BUILD, exist_ok=True)

    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", mode,
        "--name", NAME,
        "--icon", os.path.join(common.UI, "app.ico"),
        "--add-data", "%s;ui" % common.UI,
        "--add-data", "%s;models" % common.MODELS,
        "--add-data", "%s;engine" % common.ENGINE,
        "--add-data", "%s;_ffmpeg" % ff,
        "--collect-submodules", "onnxruntime",
        # engine/ 是作为数据文件打进去、运行时才 import 的，
        # PyInstaller 静态分析看不到它依赖的包，必须显式声明
        "--hidden-import", "numpy",
        "--hidden-import", "soundfile",
        "--hidden-import", "imageio_ffmpeg",
        "--collect-submodules", "soundfile",
        "--distpath", common.DIST,
        "--workpath", common.BUILD,
        "--specpath", common.BUILD,
    ]
    for m in ("torch", "torchaudio", "matplotlib", "librosa", "scipy", "pandas",
              "tkinter", "PyQt5", "PySide2", "IPython", "pytest", "PIL",
              "faster_whisper", "ctranslate2", "av", "numpy.f2py"):
        args += ["--exclude-module", m]
    args.append(os.path.join(common.APP, "entry.py"))

    print("=== PyInstaller %s ===" % mode)
    if subprocess.run(args, cwd=common.ROOT).returncode != 0:
        raise SystemExit("PyInstaller 失败")

    outdir = os.path.join(common.DIST, NAME)
    if os.path.isdir(outdir):
        os.makedirs(os.path.join(outdir, "library"), exist_ok=True)
        total = sum(os.path.getsize(os.path.join(b, f))
                    for b, _, fs in os.walk(outdir) for f in fs)
        print("\n完成: %s\n总大小: %.0f MB" % (outdir, total / 1e6))
    else:
        exe = os.path.join(common.DIST, NAME + ".exe")
        print("\n完成: %s  %.0f MB" % (exe, os.path.getsize(exe) / 1e6))


if __name__ == "__main__":
    main()

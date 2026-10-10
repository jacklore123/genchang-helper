#!/usr/bin/env python3
"""「跟唱助手」打包入口（PyInstaller 用）。

负责：
  1. 把随包携带的 ffmpeg 路径告诉 imageio-ffmpeg
  2. 启动 app/server.py 里的本地服务
"""
import os
import sys

if getattr(sys, "frozen", False):
    BASE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
    # 随包 ffmpeg
    for cand in ("ffmpeg.exe", "ffmpeg-win-x86_64-v7.1.exe"):
        p = os.path.join(BASE, "_ffmpeg", cand)
        if os.path.isfile(p):
            os.environ["IMAGEIO_FFMPEG_EXE"] = p
            break
    else:
        ffdir = os.path.join(BASE, "_ffmpeg")
        if os.path.isdir(ffdir):
            for f in os.listdir(ffdir):
                if f.lower().endswith(".exe"):
                    os.environ["IMAGEIO_FFMPEG_EXE"] = os.path.join(ffdir, f)
                    break
    sys.path.insert(0, BASE)
    sys.path.insert(0, os.path.join(BASE, "engine"))
else:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import server  # noqa: E402

if __name__ == "__main__":
    try:
        server.main()
    except Exception:
        import traceback
        traceback.print_exc()
        try:
            input("\n出错了，按回车关闭…")
        except Exception:
            pass

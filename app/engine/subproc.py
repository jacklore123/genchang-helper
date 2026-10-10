"""统一的子进程调用 —— 保证在打包成无控制台程序后不会闪黑窗。

PyInstaller 用 --noconsole 打包后，程序本身没有控制台；
但只要它再启动一个控制台程序（比如 ffmpeg），Windows 就会**新建一个
控制台窗口**，用户看到的就是"屏幕一闪一闪的 cmd 黑框"。

CREATE_NO_WINDOW 标志可以阻止这件事。
"""
from __future__ import annotations

import os
import subprocess

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def run(cmd, **kw):
    if os.name == "nt":
        kw.setdefault("creationflags", CREATE_NO_WINDOW)
        si = kw.setdefault("startupinfo", subprocess.STARTUPINFO())
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0            # SW_HIDE
    return subprocess.run(cmd, **kw)


def popen(cmd, **kw):
    if os.name == "nt":
        kw.setdefault("creationflags", CREATE_NO_WINDOW)
    return subprocess.Popen(cmd, **kw)

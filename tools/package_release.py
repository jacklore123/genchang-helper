"""把构建产物打包成可直接分发的 zip。"""
import os
import sys
import zipfile

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
RELEASE = os.path.join(ROOT, "发布")
sys.path.insert(0, TOOLS)
import push_to_github as P  # noqa: E402


def zip_dir(src, out, arc_root=""):
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for base, _, files in os.walk(src):
            for f in files:
                full = os.path.join(base, f)
                rel = os.path.relpath(full, src).replace("\\", "/")
                z.write(full, (arc_root + "/" + rel) if arc_root else rel)
                n += 1
    print("%s  (%d 个文件, %.1f MB)" % (out, n, os.path.getsize(out) / 1e6))


def zip_source(out):
    """只打源码（排除音频/模型/程序），方便用 GitHub 网页版拖拽上传。"""
    files = P.collect_files(ROOT)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for full, rel in files:
            z.write(full, rel)
    print("%s  (%d 个文件, %.1f MB)" % (out, len(files), os.path.getsize(out) / 1e6))
    return files


BAT = """@echo off
chcp 65001 >nul
title 上传「跟唱助手」到 GitHub
cd /d "%~dp0"
echo.
echo   即将把源码上传到你的 GitHub。
echo   需要一个 Token（勾选 repo 权限）：https://github.com/settings/tokens
echo   Token 只在本机使用，不会外传。上传完请立即删除它。
echo.
python "%~dp0tools\\push_to_github.py" --repo genchang-helper
echo.
pause
"""


def main():
    os.makedirs(RELEASE, exist_ok=True)
    dist = os.path.join(ROOT, "dist", "跟唱助手")
    if os.path.isdir(dist):
        zip_dir(dist, os.path.join(RELEASE, "跟唱助手-Windows版.zip"), "跟唱助手")
    apk = os.path.join(RELEASE, "跟唱助手.apk")
    if os.path.isfile(apk):
        print("%s  (%.1f MB)" % (apk, os.path.getsize(apk) / 1e6))
    zip_source(os.path.join(RELEASE, "跟唱助手-源码.zip"))
    with open(os.path.join(RELEASE, "一键上传到GitHub.bat"), "w", encoding="utf-8") as f:
        f.write(BAT)
    print("\n发布目录:", RELEASE)
    for f in sorted(os.listdir(RELEASE)):
        p = os.path.join(RELEASE, f)
        if os.path.isfile(p):
            print("   %8.1f MB  %s" % (os.path.getsize(p) / 1e6, f))


if __name__ == "__main__":
    main()


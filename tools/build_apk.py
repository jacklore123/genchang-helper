#!/usr/bin/env python3
"""打包安卓 APK —— 不需要 Gradle，直接用 aapt2 / javac / d8 / zipalign / apksigner。

    python tools/build_apk.py

依赖：JDK 17、Android SDK (build-tools;34.0.0 + platforms;android-34)
    用 JAVA_HOME / ANDROID_SDK 指定；或放在 .build/jdk、.build/sdk 下。

两个必须知道的坑（本脚本已处理）：
  1. aapt2 读不了含中文的参数路径 —— 所以中间产物全部落在纯 ASCII 工作目录
  2. APK 内置资源的目录名也不能含中文 —— 歌曲用 song1/song2，显示名写在 song.json

产物：发布/跟唱助手.apk
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

def _first_dir(*cands):
    for c in cands:
        if c and os.path.isdir(c):
            return c
    return cands[-1] if cands else None


SDK = _first_dir(
    os.environ.get("ANDROID_SDK"),
    os.environ.get("ANDROID_HOME"),
    os.path.join(common.BUILD, "sdk"),
    os.path.join(os.path.dirname(common.ROOT), "_build", "sdk"),
    os.path.join(common.ROOT, "sdk"),
) or ""

JDK = os.environ.get("JAVA_HOME") or ""
if not JDK:
    for jroot in (os.path.join(common.BUILD, "jdk"),
                  os.path.join(os.path.dirname(common.ROOT), "_build", "jdk")):
        if os.path.isdir(jroot):
            for d in sorted(os.listdir(jroot)):
                JDK = os.path.join(jroot, d)
                break
        if JDK:
            break

EXE = ".exe" if os.name == "nt" else ""
BT = os.path.join(SDK, "build-tools", "34.0.0")
ANDROID_JAR_SRC = os.path.join(SDK, "platforms", "android-34", "android.jar")
AAPT2 = os.path.join(BT, "aapt2" + EXE)
ZIPALIGN = os.path.join(BT, "zipalign" + EXE)
APKSIGNER = os.path.join(BT, "apksigner.bat" if os.name == "nt" else "apksigner")
D8 = os.path.join(BT, "d8.bat" if os.name == "nt" else "d8")
JAVAC = os.path.join(JDK, "bin", "javac" + EXE)
KEYTOOL = os.path.join(JDK, "bin", "keytool" + EXE)

WORK = os.environ.get("GENCHANG_WORK") or (
    r"C:\gcbuild" if os.name == "nt" else "/tmp/gcbuild")
APKWORK = os.path.join(WORK, "apk")
OUT = common.RELEASE
APPNAME = "跟唱助手"
AUDIO_EXT = (".m4a", ".mp3", ".wav", ".flac", ".ogg", ".opus", ".aac")
SIDE_EXT = (".lrc",)


def run(cmd, **kw):
    print("  $", " ".join(str(c) for c in cmd)[:200])
    env = dict(os.environ)
    env["JAVA_HOME"] = JDK
    env["PATH"] = os.path.join(JDK, "bin") + os.pathsep + env.get("PATH", "")
    kw.setdefault("env", env)
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", **kw)
    if r.returncode != 0:
        print("STDOUT:", (r.stdout or "")[-3000:])
        print("STDERR:", (r.stderr or "")[-3000:])
        raise SystemExit("命令失败(%d): %s" % (r.returncode, cmd[0]))
    if (r.stdout or "").strip():
        print("   ", r.stdout.strip()[:1200])
    return r


def sync_assets():
    """界面 + 歌曲库 → android/assets（歌曲目录用 ASCII 名）。"""
    assets = os.path.join(common.ANDROID, "assets")
    ui_dst = os.path.join(assets, "ui")
    shutil.rmtree(ui_dst, ignore_errors=True)
    os.makedirs(ui_dst, exist_ok=True)
    for f in ("index.html", "app.ico"):
        src = os.path.join(common.UI, f)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(ui_dst, f))

    songs_dst = os.path.join(assets, "songs")
    shutil.rmtree(songs_dst, ignore_errors=True)
    os.makedirs(songs_dst, exist_ok=True)

    n = 0
    if os.path.isdir(common.LIBRARY):
        for name in sorted(os.listdir(common.LIBRARY)):
            d = os.path.join(common.LIBRARY, name)
            if not os.path.isdir(d) or name.startswith("_"):
                continue
            kept = [f for f in os.listdir(d) if f.lower().endswith(AUDIO_EXT)]
            if not kept:
                continue
            ascii_id = "song%d" % (n + 1)
            dst = os.path.join(songs_dst, ascii_id)
            os.makedirs(dst, exist_ok=True)
            for f in kept:
                shutil.copy2(os.path.join(d, f), os.path.join(dst, f))
            for f in os.listdir(d):
                if f.lower().endswith(SIDE_EXT):
                    shutil.copy2(os.path.join(d, f), os.path.join(dst, f))
            meta = {}
            mp = os.path.join(d, "song.json")
            if os.path.isfile(mp):
                try:
                    meta = json.load(open(mp, encoding="utf-8"))
                except Exception:
                    meta = {}
            meta["name"] = meta.get("name") or name
            with open(os.path.join(dst, "song.json"), "w", encoding="utf-8") as fh:
                json.dump(meta, fh, ensure_ascii=False, indent=2)
            n += 1
            print("  歌曲 -> %s  «%s»  (%d 个音频)" % (ascii_id, meta["name"], len(kept)))
    if n == 0:
        print("  [!] library/ 里没有歌曲，APK 将不含内置歌曲（仍可用手机导入）")
    return n


def mirror_to_ascii():
    dst = os.path.join(APKWORK, "src_tree")
    shutil.rmtree(dst, ignore_errors=True)
    os.makedirs(dst)
    shutil.copy2(os.path.join(common.ANDROID, "AndroidManifest.xml"), dst)
    for sub in ("res", "assets", "src"):
        s = os.path.join(common.ANDROID, sub)
        if os.path.isdir(s):
            shutil.copytree(s, os.path.join(dst, sub))
    return dst


def find_java_sources(*roots):
    out = []
    for src in roots:
        for base, _, files in os.walk(src):
            out += [os.path.join(base, f) for f in files if f.endswith(".java")]
    return out


def main():
    for p, name in ((AAPT2, "aapt2"), (ANDROID_JAR_SRC, "android.jar"), (JAVAC, "javac"),
                    (D8, "d8"), (ZIPALIGN, "zipalign"), (APKSIGNER, "apksigner")):
        if not os.path.exists(p):
            raise SystemExit("缺少 %s: %s" % (name, p))

    print("=== 0 准备 ===")
    print("  ASCII 工作目录: %s" % WORK)
    os.makedirs(WORK, exist_ok=True)
    platform = os.path.join(WORK, "android.jar")
    if not os.path.exists(platform):
        shutil.copy2(ANDROID_JAR_SRC, platform)

    sync_assets()
    shutil.rmtree(APKWORK, ignore_errors=True)
    os.makedirs(APKWORK)
    tree = mirror_to_ascii()
    res_dir = os.path.join(tree, "res")
    assets_dir = os.path.join(tree, "assets")
    manifest = os.path.join(tree, "AndroidManifest.xml")
    os.makedirs(OUT, exist_ok=True)

    print("=== 1 生成图标 ===")
    png = os.path.join(res_dir, "drawable", "icon.png")
    os.makedirs(os.path.dirname(png), exist_ok=True)
    import make_icon
    make_icon.make_png(png, 432)

    print("=== 2 aapt2 compile ===")
    res_zip = os.path.join(APKWORK, "res.zip")
    run([AAPT2, "compile", "--dir", res_dir, "-o", res_zip])

    print("=== 3 aapt2 link ===")
    base_apk = os.path.join(APKWORK, "base.apk")
    run([AAPT2, "link", "-o", base_apk,
         "-I", platform,
         "--manifest", manifest,
         "-R", res_zip,
         "-A", assets_dir,
         "--java", os.path.join(APKWORK, "gen"),
         "--min-sdk-version", "24",
         "--target-sdk-version", "34",
         "--version-code", "1", "--version-name", "1.0",
         "--auto-add-overlay"], cwd=APKWORK)

    print("=== 4 javac ===")
    classes = os.path.join(APKWORK, "classes")
    os.makedirs(classes, exist_ok=True)
    sources = find_java_sources(os.path.join(tree, "src"), os.path.join(APKWORK, "gen"))
    if not sources:
        raise SystemExit("没有找到 Java 源码")
    run([JAVAC, "-encoding", "UTF-8", "-source", "8", "-target", "8",
         "-bootclasspath", platform, "-classpath", platform, "-d", classes] + sources)

    print("=== 5 d8 (dex) ===")
    class_files = [os.path.join(b, f) for b, _, fs in os.walk(classes) for f in fs
                   if f.endswith(".class")]
    run([D8, "--lib", platform, "--min-api", "24", "--output", APKWORK] + class_files)
    dex = os.path.join(APKWORK, "classes.dex")
    if not os.path.exists(dex):
        raise SystemExit("没有生成 classes.dex")

    print("=== 6 把 dex 塞进 apk ===")
    with zipfile.ZipFile(base_apk, "a", zipfile.ZIP_DEFLATED) as z:
        z.write(dex, "classes.dex")

    print("=== 7 zipalign ===")
    aligned = os.path.join(APKWORK, "aligned.apk")
    run([ZIPALIGN, "-f", "-p", "4", base_apk, aligned])

    print("=== 8 签名 ===")
    ks = os.environ.get("GENCHANG_KEYSTORE") or os.path.join(WORK, "genchang.jks")
    if not os.path.exists(ks):
        run([KEYTOOL, "-genkeypair", "-keystore", ks, "-alias", "genchang",
             "-keyalg", "RSA", "-keysize", "2048", "-validity", "10950",
             "-storepass", "genchang123", "-keypass", "genchang123",
             "-dname", "CN=GenChang, OU=Class, O=School, L=City, ST=State, C=CN"])
    out_apk = os.path.join(OUT, APPNAME + ".apk")
    if os.path.exists(out_apk):
        os.remove(out_apk)
    run([APKSIGNER, "sign", "--ks", ks, "--ks-pass", "pass:genchang123",
         "--key-pass", "pass:genchang123", "--ks-key-alias", "genchang",
         "--out", out_apk, aligned])
    run([APKSIGNER, "verify", "--print-certs", out_apk])
    print("\n完成: %s  (%.1f MB)" % (out_apk, os.path.getsize(out_apk) / 1e6))


if __name__ == "__main__":
    main()

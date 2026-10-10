#!/usr/bin/env python3
"""一站式入口：把一首歌变成「跟唱包」（原唱 + 伴奏，一键切换）。

三种用法：

  1) 只有原唱，AI 分离出伴奏
     python tools/make_pack.py 歌曲.mp3 --name "歌名"

  2) 已有官方伴奏，自动对齐后打包（音质最好）
     python tools/make_pack.py 原唱.mp4 --accompaniment 伴奏.mp4 --name "歌名"

  3) 批量处理 songs/ 目录下所有歌（GitHub Actions 工作流就是这么调的）
     python tools/make_pack.py --scan

产物在 library/<歌名>/ 下：original.m4a、instrumental.m4a、vocals.m4a、song.json
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

sys.path.insert(0, common.ENGINE)

AUDIO_EXT = (".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma",
             ".mp4", ".mkv", ".mov", ".avi", ".webm", ".ts")


def ensure_model():
    if common.model_path():
        return common.model_path()
    print("没有找到分离模型，先下载…")
    import fetch_model
    fetch_model.main()
    return common.model_path()


def build_one(src, name, accompaniment=None, note=""):
    if accompaniment:
        import build_pair
        print(f"\n=== {name}：官方伴奏模式（自动对齐）===")
        return build_pair.build_pair(src, accompaniment, common.LIBRARY, name,
                                     note=note or "原唱 + 伴奏")
    import build_pack
    print(f"\n=== {name}：AI 分离模式 ===")
    return build_pack.build(src, common.LIBRARY, name, ensure_model(),
                            progress=lambda m: print("   ", m))


def scan():
    """处理 songs/ 下的目录：每个目录一个歌，含 voice.* 与 accomp.* 则用官方伴奏模式。"""
    if not os.path.isdir(common.SONGS):
        print("没有 songs/ 目录")
        return 0
    n = 0
    for d in sorted(os.listdir(common.SONGS)):
        full = os.path.join(common.SONGS, d)
        if not os.path.isdir(full):
            continue
        files = [f for f in os.listdir(full) if f.lower().endswith(AUDIO_EXT)]
        if not files:
            continue
        voice = next((f for f in files if f.lower().startswith(("voice", "vocal", "原唱"))), None)
        accomp = next((f for f in files if f.lower().startswith(("accomp", "inst", "伴奏"))), None)
        if voice is None:
            voice = sorted(files)[0]
        vp = os.path.join(full, voice)
        ap = os.path.join(full, accomp) if accomp else None
        build_one(vp, d, ap)
        n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", nargs="?", help="原唱音频/视频文件")
    ap.add_argument("--name", help="歌曲名（默认取文件名）")
    ap.add_argument("--accompaniment", help="伴奏文件（用了它就不再 AI 分离，直接对齐）")
    ap.add_argument("--note", default="", help="写进 song.json 的说明")
    ap.add_argument("--scan", action="store_true", help="批量处理 songs/ 目录")
    ap.add_argument("--out", default=None, help="输出目录（默认 library/）")
    args = ap.parse_args()

    os.makedirs(common.LIBRARY, exist_ok=True)
    if args.scan:
        n = scan()
        print(f"\n共处理 {n} 首")
        return
    if not args.input:
        ap.error("需要给出输入文件，或用 --scan")
    name = args.name or os.path.splitext(os.path.basename(args.input))[0]
    build_one(args.input, name, args.accompaniment, args.note)


if __name__ == "__main__":
    main()

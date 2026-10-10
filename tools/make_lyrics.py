#!/usr/bin/env python3
"""把一份歌词对齐到某首歌的实际录音上（命令行版，界面里也有这个功能）。

    python tools/make_lyrics.py library/歌名 lyrics/某某.lrc
    python tools/make_lyrics.py --all lyrics/某某.lrc      # 给 library 里所有歌都对齐

支持两种输入：
  * 标准 LRC（带时间轴）→ 估全局偏移 + 逐行 DP 微调
  * 纯文本（一行一句，无时间轴）→ 按人声活跃区间均分

产物：<跟唱包>/lyrics.lrc
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

sys.path.insert(0, common.ENGINE)
import align_lyrics  # noqa: E402


def process(pack, lrc):
    anchor = align_lyrics.pick_anchor(pack)
    if not anchor:
        print("  跳过（没有音频）:", pack)
        return False
    print("  对齐音频:", os.path.basename(anchor))
    info = align_lyrics.align(anchor, lrc, os.path.join(pack, "lyrics.lrc"),
                              progress=lambda m: print("   ", m))
    print("  → %d 行，偏移 %+.2fs%s" % (info["lines"], info["offset"],
                                       "" if info["timed"] else "（纯文本均分）"))
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pack", nargs="?", help="跟唱包目录（或 library 下的名字）")
    ap.add_argument("lrc", help="歌词文件（.lrc 或纯文本）")
    ap.add_argument("--all", action="store_true", help="对 library 下所有歌都用这份歌词")
    a = ap.parse_args()

    if a.all:
        n = 0
        for name in sorted(os.listdir(common.LIBRARY)):
            d = os.path.join(common.LIBRARY, name)
            if os.path.isdir(d) and not name.startswith("_"):
                print("处理", name)
                n += 1 if process(d, a.lrc) else 0
        print("完成 %d 首" % n)
        return
    if not a.pack:
        ap.error("需要给出跟唱包目录，或用 --all")
    pack = a.pack if os.path.isdir(a.pack) else os.path.join(common.LIBRARY, a.pack)
    process(pack, a.lrc)


if __name__ == "__main__":
    main()

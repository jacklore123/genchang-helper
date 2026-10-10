#!/usr/bin/env python3
"""把歌词时间轴对齐到某首歌的实际录音上。

官方 LRC 是给官方发行版写的；如果你手上是另一次录音（不同语言版本、
不同母带），直接套用会整体偏移。这个脚本用**分离出来的人声轨**做锚点：
先估一个全局偏移，再用动态规划把每一行微调到人声起音上。

    python tools/make_lyrics.py library/歌名 lyrics/紫荆花盛开.lrc
    python tools/make_lyrics.py --all lyrics/紫荆花盛开.lrc     # 给 library 里所有歌都对齐

产物：<跟唱包>/lyrics.lrc（带对齐后的时间轴）
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

SR = 16000
HOP = 320          # 20 ms
LINE_RE = re.compile(r"^\[(\d+):(\d+(?:\.\d+)?)\](.*)$")


# --------------------------------------------------------------------------- #
def read_lrc(path):
    """返回 (meta_lines, [{'t':秒, 'text':...}])，保留 @歌手 标记行。"""
    meta, lines = [], []
    for raw in open(path, encoding="utf-8-sig").read().splitlines():
        s = raw.strip()
        if not s:
            continue
        m = LINE_RE.match(s)
        if not m:
            if s.startswith("[") and ":" not in s.split("]")[0]:
                meta.append(s)
            continue
        t = int(m.group(1)) * 60 + float(m.group(2))
        lines.append({"t": t, "text": m.group(3).strip()})
    lines.sort(key=lambda x: x["t"])
    return meta, lines


def write_lrc(path, meta, lines):
    out = list(meta)
    for ln in lines:
        t = max(0.0, ln["t"])
        mm = int(t // 60)
        ss = t - mm * 60
        out.append("[%02d:%05.2f]%s" % (mm, ss, ln["text"]))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")


def decode_mono(path, sr=SR):
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    tmp = os.path.join(common.BUILD, "_lyr.f32")
    os.makedirs(common.BUILD, exist_ok=True)
    subprocess.run([ff, "-y", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(sr),
                    "-f", "f32le", tmp], check=True)
    x = np.fromfile(tmp, dtype="<f4")
    try:
        os.remove(tmp)
    except OSError:
        pass
    return x


def envelope(x, nfft=1024, hop=HOP):
    """对数能量的正向差分（起音强度），归一到 0..1。"""
    win = np.hanning(nfft).astype(np.float32)
    n = 1 + (len(x) - nfft) // hop
    if n <= 2:
        return np.zeros(max(n, 1), np.float32)
    fr = np.lib.stride_tricks.sliding_window_view(x, nfft)[::hop][:n] * win
    e = np.log1p(np.abs(np.fft.rfft(fr, axis=-1)).sum(1) * 50.0)
    d = np.maximum(0, np.diff(e))
    d = np.concatenate([[0], d])
    return (d / (d.max() + 1e-9)).astype(np.float32)


def smooth(v, k=9):
    if k <= 1:
        return v
    ker = np.hanning(k).astype(np.float32)
    ker /= ker.sum()
    return np.convolve(v, ker, mode="same")


def global_offset(env, times, max_shift=8.0):
    """把歌词行时刻做成脉冲串，与起音包络做互相关，估全局偏移。"""
    fps = SR / HOP
    n = len(env)
    imp = np.zeros(n, np.float32)
    for t in times:
        i = int(round(t * fps))
        if 0 <= i < n:
            imp[i] = 1.0
    imp = smooth(imp, 3)
    e = smooth(env, 3) - float(env.mean())
    m = int(max_shift * fps)
    k = 1 << int(np.ceil(np.log2(2 * n)))
    c = np.fft.irfft(np.fft.rfft(e, k) * np.conj(np.fft.rfft(imp, k)), k)
    c = np.concatenate([c[-m:], c[:m + 1]])
    lags = np.arange(-m, m + 1)
    # c[k] = Σ env[i+k]·imp[i] → 峰值 k 表示歌词要整体 +k/fps
    best = int(lags[int(np.argmax(c))])
    return best / fps


def align_lines(env, lines, offset, window=1.2, min_gap=0.25, fps=SR / HOP):
    """动态规划把每行微调到起音上，且保持单调。"""
    cand = []
    for ln in lines:
        center = ln["t"] + offset
        lo = max(0.0, center - window)
        hi = max(0.0, center + window)
        idx = np.arange(int(lo * fps), int(hi * fps) + 1)
        idx = idx[(idx >= 0) & (idx < len(env))]
        cand.append(idx)
    n = len(lines)
    if n == 0:
        return []
    INF = 1e18
    dp = [np.full(len(c), INF) for c in cand]
    bk = [np.full(len(c), -1, np.int32) for c in cand]

    for j, i in enumerate(cand[0]):
        t = i / fps
        dp[0][j] = abs(t - (lines[0]["t"] + offset)) * 2.0 - env[i] * 1.5
    for li in range(1, n):
        prev_t = cand[li - 1] / fps
        cur_t = cand[li] / fps
        for j, i in enumerate(cand[li]):
            tt = cur_t[j]
            base = abs(tt - (lines[li]["t"] + offset)) * 2.0 - env[i] * 1.5
            # 只允许从前一个"至少早 min_gap"的候选转移
            valid = np.where(prev_t <= tt - min_gap)[0]
            if len(valid) == 0:
                continue
            k = valid[int(np.argmin(dp[li - 1][valid]))]
            dp[li][j] = base + dp[li - 1][k]
            bk[li][j] = k
    j = int(np.argmin(dp[n - 1]))
    out = [0.0] * n
    for li in range(n - 1, -1, -1):
        out[li] = cand[li][j] / fps
        j = int(bk[li][j]) if li > 0 and bk[li][j] >= 0 else max(0, j)
    return out


def pick_anchor(pack):
    d = pack if os.path.isdir(pack) else os.path.join(common.LIBRARY, pack)
    for name in ("vocals.m4a", "vocals.mp3", "vocals.wav", "vocals.flac",
                 "instrumental.m4a", "instrumental.mp3", "instrumental.wav", "original.m4a"):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return d, p
    return d, None


def process(pack_arg, lrc_path, quiet=False):
    pack, anchor = pick_anchor(pack_arg)
    if not anchor:
        print("  跳过（没有音频）:", pack)
        return False
    meta, lines = read_lrc(lrc_path)
    if not lines:
        print("  歌词为空:", lrc_path)
        return False
    x = decode_mono(anchor)
    env = envelope(x)
    dur = len(x) / SR
    times = [ln["t"] for ln in lines if not ln["text"].startswith("@")]
    off = global_offset(env, times)
    newtimes = align_lines(env, lines, off)
    moved = [round(n - (l["t"] + off), 2) for n, l in zip(newtimes, lines)]
    for ln, t in zip(lines, newtimes):
        ln["t"] = round(t, 2)
    out = os.path.join(pack, "lyrics.lrc")
    write_lrc(out, meta, lines)
    if not quiet:
        print("  %s  时长 %.1fs  全局偏移 %+.2fs" % (os.path.basename(pack), dur, off))
        print("  写入 %s（%d 行）" % (out, len(lines)))
        print("  前 6 行：")
        for ln in lines[:6]:
            print("    %6.2f  %s" % (ln["t"], ln["text"]))
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pack", nargs="?", help="跟唱包目录（或 library 下的名字）")
    ap.add_argument("lrc", help="原始 LRC 文件")
    ap.add_argument("--all", action="store_true", help="对 library 下所有歌都用同一个歌词")
    a = ap.parse_args()

    if a.all:
        n = 0
        for name in sorted(os.listdir(common.LIBRARY)):
            d = os.path.join(common.LIBRARY, name)
            if os.path.isdir(d) and not name.startswith("_"):
                print("处理", name)
                n += 1 if process(d, a.lrc) else 0
        print("完成 %d 首" % n)
    else:
        if not a.pack:
            ap.error("需要给出跟唱包目录，或用 --all")
        process(a.pack, a.lrc)


if __name__ == "__main__":
    main()

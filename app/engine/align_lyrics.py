#!/usr/bin/env python3
"""歌词自动并轨：把一份 LRC 对齐到某个跟唱包的实际录音上。

官方歌词的时间轴是给官方发行版写的，换了录音（不同语言版本、不同母带）
就会整体偏几秒。这里用分离出来的人声轨当锚点：
  1. 先把歌词行做成脉冲串，与起音包络做互相关 —— 估一个全局偏移
  2. 再用动态规划把每一行微调到真实起音上（保持单调、不越界）

对纯旋律/清唱也能用，因为它只看起音强度，不依赖音色。
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile

import numpy as np

SR = 16000
HOP = 320                                  # 20 ms
LINE_RE = re.compile(r"^\[(\d+):(\d+(?:\.\d+)?)\](.*)$")
FPS = SR / HOP


# --------------------------------------------------------------------------- #
def read_lrc(path):
    """解析 LRC。'@名字' 视为演唱者标记行。返回 (meta, lines)。"""
    meta, lines = [], []
    text = ""
    for enc in ("utf-8-sig", "utf-8", "gbk", "utf-16"):
        try:
            text = open(path, encoding=enc).read()
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    if not text:
        text = open(path, encoding="utf-8", errors="replace").read()

    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            continue
        m = LINE_RE.match(s)
        if not m:
            if s.startswith("[") and "]" in s and not re.search(r"\d+:\d+", s):
                meta.append(s)
            continue
        t = int(m.group(1)) * 60 + float(m.group(2))
        body = m.group(3)
        # 支持 [mm:ss.xx][mm:ss.yy]歌词 这种一行多时间戳
        extra = []
        while True:
            m2 = LINE_RE.match(body.strip())
            if not m2:
                break
            extra.append(int(m2.group(1)) * 60 + float(m2.group(2)))
            body = m2.group(3)
        body = body.strip()
        for tt in [t] + extra:
            if not body:
                continue
            if body.startswith("@"):
                lines.append({"t": tt, "text": "", "role": body[1:].strip(), "mark": True})
            else:
                lines.append({"t": tt, "text": body, "mark": False})
    lines.sort(key=lambda x: x["t"])
    return meta, lines


def read_plain_text(path):
    """纯文本歌词：一行一句，没有时间轴。用真实录音估出起唱点后再均分。"""
    text = ""
    for enc in ("utf-8-sig", "utf-8", "gbk", "utf-16"):
        try:
            text = open(path, encoding=enc).read()
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    if not text:
        text = open(path, encoding="utf-8", errors="replace").read()
    lines = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s or s.startswith("["):
            continue
        lines.append({"t": 0.0, "text": s, "mark": False})
    return [], lines


def write_lrc(path, meta, lines):
    out = list(meta)
    for ln in lines:
        t = max(0.0, ln["t"])
        mm = int(t // 60)
        ss = t - mm * 60
        body = ("@" + ln["role"]) if ln.get("mark") else ln["text"]
        out.append("[%02d:%05.2f]%s" % (mm, ss, body))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")


# --------------------------------------------------------------------------- #
def decode_mono(path, sr=SR):
    import imageio_ffmpeg
    import subproc
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    fd, tmp = tempfile.mkstemp(suffix=".f32")
    os.close(fd)
    try:
        subproc.run([ff, "-y", "-v", "error", "-i", path, "-vn", "-ac", "1",
                     "-ar", str(sr), "-f", "f32le", tmp], check=True)
        return np.fromfile(tmp, dtype="<f4")
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def envelope(x, nfft=1024, hop=HOP):
    """起音强度包络，归一到 0..1。"""
    win = np.hanning(nfft).astype(np.float32)
    n = 1 + (len(x) - nfft) // hop
    if n <= 2:
        return np.zeros(max(n, 1), np.float32)
    fr = np.lib.stride_tricks.sliding_window_view(x, nfft)[::hop][:n] * win
    e = np.log1p(np.abs(np.fft.rfft(fr, axis=-1)).sum(1) * 50.0)
    d = np.maximum(0, np.diff(e))
    d = np.concatenate([[0], d])
    return (d / (d.max() + 1e-9)).astype(np.float32)


def _smooth(v, k=9):
    if k <= 1:
        return v
    ker = np.hanning(k).astype(np.float32)
    ker /= ker.sum()
    return np.convolve(v, ker, mode="same")


def voiced_span(env, thresh=0.18, min_gap=1.5):
    """估出"真正在唱"的时间范围（跳过前奏和尾奏静音）。"""
    if len(env) == 0:
        return 0.0, 0.0
    on = env > thresh
    idx = np.where(on)[0]
    if len(idx) == 0:
        return 0.0, len(env) / FPS
    # 从两端找第一段连续活跃区
    start = idx[0]
    end = idx[-1]
    return start / FPS, end / FPS


def global_offset(env, times, max_shift=10.0):
    """歌词脉冲串 × 起音包络 的互相关峰值，作为全局偏移。"""
    n = len(env)
    if n == 0 or not times:
        return 0.0
    imp = np.zeros(n, np.float32)
    for t in times:
        i = int(round(t * FPS))
        if 0 <= i < n:
            imp[i] = 1.0
    imp = _smooth(imp, 3)
    e = _smooth(env, 5) - float(env.mean())
    m = int(max_shift * FPS)
    k = 1 << int(np.ceil(np.log2(2 * n)))
    c = np.fft.irfft(np.fft.rfft(e, k) * np.conj(np.fft.rfft(imp, k)), k)
    c = np.concatenate([c[-m:], c[:m + 1]])
    lags = np.arange(-m, m + 1)
    return float(lags[int(np.argmax(c))]) / FPS


def align_lines(env, lines, offset, window=1.5, min_gap=0.25):
    """DP：把每行吸附到起音上，保持单调。"""
    n = len(lines)
    if n == 0:
        return []
    cands = []
    for ln in lines:
        center = ln["t"] + offset
        lo = max(0, int((center - window) * FPS))
        hi = min(len(env) - 1, int((center + window) * FPS))
        idx = np.arange(lo, hi + 1)
        if len(idx) == 0:
            idx = np.array([max(0, min(len(env) - 1, int(center * FPS)))])
        cands.append(idx)
    INF = 1e18
    dp = [np.full(len(c), INF, np.float64) for c in cands]
    bk = [np.full(len(c), -1, np.int32) for c in cands]
    for j, i in enumerate(cands[0]):
        dp[0][j] = abs(i / FPS - (lines[0]["t"] + offset)) * 2.0 - env[i] * 1.5
    for li in range(1, n):
        prev = cands[li - 1] / FPS
        for j, i in enumerate(cands[li]):
            tt = i / FPS
            base = abs(tt - (lines[li]["t"] + offset)) * 2.0 - env[i] * 1.5
            ok = np.where(prev <= tt - min_gap)[0]
            if len(ok) == 0:
                continue
            k = ok[int(np.argmin(dp[li - 1][ok]))]
            dp[li][j] = base + dp[li - 1][k]
            bk[li][j] = k
    j = int(np.argmin(dp[n - 1]))
    out = [0.0] * n
    for li in range(n - 1, -1, -1):
        out[li] = cands[li][j] / FPS
        j = int(bk[li][j]) if li > 0 and bk[li][j] >= 0 else max(0, j)
    return out


def onset_candidates(env, min_gap_s=0.9, thresh=0.10):
    """找出可能的"句子起点"：包络局部极大值，且彼此至少隔 min_gap。"""
    if len(env) == 0:
        return np.array([], dtype=np.int64)
    e = _smooth(env, 5)
    gap = max(1, int(min_gap_s * FPS))
    order = np.argsort(e)[::-1]
    chosen = []
    for i in order:
        if e[i] < thresh:
            break
        if all(abs(int(i) - j) >= gap for j in chosen):
            chosen.append(int(i))
        if len(chosen) >= 400:
            break
    return np.array(sorted(chosen), dtype=np.int64)


def distribute_to_onsets(env, lines, span=None):
    """纯文本歌词：把每一句吸附到真实的起音句点上（而不是死板均分）。

    用 DP 从候选起音里挑出 N 个，使总"代价"最小：
      - 优先选包络强的地方
      - 相邻两句至少隔 min_gap
    候选不够时退回均分。
    """
    n = len(lines)
    if n == 0:
        return []
    s, e = span if span else voiced_span(env)
    if e <= s:
        s, e = 0.0, max(10.0, len(env) / FPS)
    lo, hi = int(s * FPS), int(e * FPS)
    cand = onset_candidates(env)
    cand = cand[(cand >= lo) & (cand <= hi)]
    if len(cand) < n:
        step = (e - s) / max(1, n)
        return [s + i * step for i in range(n)]

    m = len(cand)
    ctimes = cand / FPS
    # 时间先验：均匀分布下的"预期位置"，让每句吸附到它附近最强的起音，
    # 而不是跑去抓全曲最强的峰
    expected = np.array([s + (k + 0.5) * (e - s) / n for k in range(n)])
    strg = env[cand] * 1.6

    NEG = 1e9
    dp = np.full((n, m), NEG, np.float64)
    bk = np.full((n, m), -1, np.int32)
    dp[0] = np.abs(ctimes - expected[0]) * 2.0 - strg
    min_gap = int(0.9 * FPS)
    for k in range(1, n):
        run_best, run_arg = np.inf, -1
        j = 0
        for i in range(m):
            while j < i and cand[i] - cand[j] >= min_gap:
                if dp[k - 1][j] < run_best:
                    run_best, run_arg = dp[k - 1][j], j
                j += 1
            if run_arg >= 0 and run_best < 1e8:
                dp[k][i] = run_best + np.abs(ctimes[i] - expected[k]) * 2.0 - strg[i]
                bk[k][i] = run_arg
    last = int(np.argmin(dp[n - 1]))
    if dp[n - 1][last] >= 1e8:
        step = (e - s) / max(1, n)
        return [s + i * step for i in range(n)]
    out = [0.0] * n
    i = last
    for k in range(n - 1, -1, -1):
        out[k] = cand[i] / FPS
        i = int(bk[k][i]) if k > 0 else -1
    return out


def distribute_plain(env, lines, span=None):
    """兼容旧接口：优先吸附起音，退不回就均分。"""
    return distribute_to_onsets(env, lines, span)


# --------------------------------------------------------------------------- #
def align(audio_path: str, lrc_path: str, out_path: str, progress=None):
    """主入口。返回信息字典。"""
    def say(m):
        if progress:
            progress(m)

    is_lrc = lrc_path.lower().endswith((".lrc", ".txt"))
    meta, lines = read_lrc(lrc_path)
    has_time = any((not l.get("mark")) and l["t"] > 0 for l in lines)
    if not has_time:
        # 当成纯文本歌词处理
        meta, lines = read_plain_text(lrc_path)
        if not lines:
            raise ValueError("歌词文件里没有可用内容")

    say("读取人声轨…")
    x = decode_mono(audio_path)
    env = envelope(x)
    dur = len(x) / SR
    say("  音频 %.1f 秒" % dur)

    if has_time:
        times = [l["t"] for l in lines if not l.get("mark")]
        off = global_offset(env, times)
        say("  全局偏移 %+.2f 秒" % off)
        newt = align_lines(env, lines, off)
        moved = [round(n - (l["t"] + off), 2) for n, l in zip(newt, lines)]
        drift = max(moved) - min(moved) if moved else 0.0
        say("  逐行微调完成（最大浮动 %.2fs）" % drift)
    else:
        s, e = voiced_span(env)
        say("  没有时间轴：人声区间 %.1f–%.1f 秒，%d 句吸附到起音" % (s, e, len(lines)))
        newt = distribute_plain(env, lines, (s, e))
        off = 0.0

    for ln, t in zip(lines, newt):
        ln["t"] = round(float(t), 2)
    write_lrc(out_path, meta, lines)
    say("  已写入 %s（%d 行）" % (os.path.basename(out_path), len(lines)))
    return {"lines": len(lines), "offset": round(off, 2), "duration": round(dur, 2),
            "timed": bool(has_time)}


def pick_anchor(pack_dir: str):
    """挑一个用来对齐的音频：优先人声轨，其次原始混音。"""
    for n in ("vocals.m4a", "vocals.mp3", "vocals.wav", "vocals.flac",
              "original.m4a", "original.mp3", "original.wav", "original.flac",
              "instrumental.m4a", "instrumental.mp3"):
        p = os.path.join(pack_dir, n)
        if os.path.isfile(p):
            return p
    for f in sorted(os.listdir(pack_dir)) if os.path.isdir(pack_dir) else []:
        if f.lower().endswith((".m4a", ".mp3", ".wav", ".flac", ".aac", ".ogg")):
            return os.path.join(pack_dir, f)
    return None

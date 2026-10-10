#!/usr/bin/env python3
"""把一对「原唱 + 伴奏」音频对齐并打成一个跟唱包。

比 AI 分离更好：如果是官方伴奏 + 官方原唱，音质零损失。
自动做时间对齐（互相关，亚采样级精修），统一增益防削波，输出 m4a。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_sep import decode, write_wav  # noqa: E402
import imageio_ffmpeg  # noqa: E402

FF = imageio_ffmpeg.get_ffmpeg_exe()
SR = 44100


# --------------------------------------------------------------------------- #
def onset_env(x: np.ndarray, sr=SR, hop=512, nfft=2048) -> np.ndarray:
    """单声道起音强度包络（对音量/音色差异不敏感）。"""
    m = x.mean(0) if x.ndim == 2 else x
    win = np.hanning(nfft).astype(np.float32)
    n = 1 + (len(m) - nfft) // hop
    if n <= 0:
        return np.zeros(0, np.float32)
    frames = np.lib.stride_tricks.sliding_window_view(m, nfft)[::hop][:n] * win
    S = np.log1p(np.abs(np.fft.rfft(frames, axis=-1)) * 100.0)
    flux = np.maximum(0, np.diff(S, axis=0)).sum(1)
    return (flux / (flux.max() + 1e-9)).astype(np.float32)


def best_lag(o: np.ndarray, a: np.ndarray, max_seconds=15.0):
    """求伴奏相对原唱的时间偏移 d（采样）。

    约定：同一段音乐，原唱在 t 出现，伴奏在 t+d 出现。
      d > 0 → 伴奏晚了 d 秒（例如 KTV 多了段前奏）
      d < 0 → 伴奏早了
    对齐就是把伴奏往前挪 d 个采样。
    """
    eo, ea = onset_env(o), onset_env(a)
    hop = 512
    L = min(len(eo), len(ea))
    o2 = eo[:L] - eo[:L].mean()
    a2 = ea[:L] - ea[:L].mean()
    n = 1 << int(np.ceil(np.log2(2 * L)))
    # c[m] = Σ o[k+m]·a[k]  →  峰值 m 满足 a[k] ≈ o[k+m]  →  d = -m
    c = np.fft.irfft(np.fft.rfft(o2, n) * np.conj(np.fft.rfft(a2, n)), n)
    maxlag = int(max_seconds * SR / hop)
    c = np.concatenate([c[-maxlag:], c[:maxlag + 1]])
    ms = np.arange(-maxlag, maxlag + 1)
    k = int(np.argmax(c))
    denom = (np.linalg.norm(o2) * np.linalg.norm(a2) + 1e-9)
    return int(-ms[k]) * hop, float(c[k] / denom)


def refine_lag(o: np.ndarray, a: np.ndarray, d: int, window_s=25.0, search_s=1.5) -> int:
    """在 d 附近用起音包络细调（步进 64 采样）。"""
    n = int(window_s * SR)
    if o.shape[-1] < n or a.shape[-1] < n + abs(d) + int(search_s * SR):
        return d
    x = o[:, :n]
    best, bd = -2.0, d
    for cand in range(d - int(search_s * SR), d + int(search_s * SR) + 1, 64):
        s = cand if cand >= 0 else 0
        if s + n > a.shape[-1]:
            continue
        A, B = onset_env(x), onset_env(a[:, s:s + n])
        L = min(len(A), len(B))
        if L < 50:
            continue
        u, v = A[:L] - A[:L].mean(), B[:L] - B[:L].mean()
        c = float(np.dot(u, v) / (np.linalg.norm(u) * np.linalg.norm(v) + 1e-9))
        if c > best:
            best, bd = c, cand
    return bd


def refine_sample(o: np.ndarray, a: np.ndarray, d: int,
                  window_s=20.0, search=4096, min_corr=0.30):
    """采样级精修：只有当两段录音确实同源（波形相关足够高）时才采纳。

    官方原唱 + 官方伴奏属于同一次母带，这一步能把误差从 ~12ms 压到 0。
    如果伴奏是另一次录音（相关接近 0），保持包络估计的结果不动。
    """
    n = int(window_s * SR)
    if o.shape[-1] < n or a.shape[-1] < n + abs(d) + search:
        return d, 0.0
    x = o[:, 0:n]
    nx = float(np.linalg.norm(x)) + 1e-9
    best, bd = -2.0, d
    for step in (16, 1):
        span = search if step == 16 else 16
        for cand in range(max(0, bd - span), bd + span + 1, step):
            if cand + n > a.shape[-1]:
                continue
            y = a[:, cand:cand + n]
            c = float(np.dot(x.ravel(), y.ravel()) / (nx * (np.linalg.norm(y) + 1e-9)))
            if c > best:
                best, bd = c, cand
    if best < min_corr:
        return d, best
    return bd, best


def apply_lag(a: np.ndarray, d: int, target_len: int) -> np.ndarray:
    """把伴奏按偏移 d 对齐到原唱起点，再裁/补到 target_len。"""
    C = a.shape[0]
    if d > 0:
        a = a[:, d:]
    elif d < 0:
        a = np.concatenate([np.zeros((C, -d), np.float32), a], axis=1)
    if a.shape[1] < target_len:
        a = np.concatenate([a, np.zeros((C, target_len - a.shape[1]), np.float32)], axis=1)
    return a[:, :target_len]


def encode_m4a(wav: str, out: str, bitrate="256k"):
    subprocess.run([FF, "-y", "-v", "error", "-i", wav, "-c:a", "aac", "-b:a", bitrate,
                    "-movflags", "+faststart", out], check=True)


# --------------------------------------------------------------------------- #
def build_pair(original: str, accomp: str, outdir: str, name: str,
               note: str = "", auto_align: bool = True, progress=print):
    pack = os.path.join(outdir, name)
    os.makedirs(pack, exist_ok=True)
    tmp = os.path.join(pack, "_tmp")
    os.makedirs(tmp, exist_ok=True)

    progress("解码原唱…")
    o = decode(original)
    progress(f"  {o.shape[1]/SR:.2f}s")
    progress("解码伴奏…")
    a = decode(accomp)
    progress(f"  {a.shape[1]/SR:.2f}s")

    lag = 0
    corr = 0.0
    if auto_align:
        progress("对齐…")
        lag, corr = best_lag(o, a)
        progress(f"  伴奏相对原唱偏移 {lag/SR:+.3f}s，相关 {corr:.3f}")
        lag2 = refine_lag(o, a, lag)
        if lag2 != lag:
            progress(f"  包络精修：{lag2/SR:+.3f}s（原 {lag/SR:+.3f}s）")
            lag = lag2
        lag3, wcorr = refine_sample(o, a, lag)
        if lag3 != lag:
            progress(f"  采样级精修：{lag3/SR:+.3f}s（波形相关 {wcorr:.3f}）→ 已对齐到采样")
            lag = lag3
        elif wcorr >= 0.30:
            progress(f"  波形相关 {wcorr:.3f}，已采样级对齐")
        else:
            progress(f"  波形相关 {wcorr:.3f}（两段录音不同源），保持包络对齐 "
                     f"±{512/SR*1000:.0f}ms")
        if lag < 0:
            progress(f"  伴奏比原唱早 {-lag/SR:.3f}s，将在开头补静音")

    n = o.shape[1]
    a = apply_lag(a, lag, n)
    if a.shape[1] != n:
        n = min(n, a.shape[1])
        o, a = o[:, :n], a[:, :n]

    peak = float(max(np.abs(o).max(), np.abs(a).max()))
    g = 0.95 / peak if peak > 0.95 else 1.0
    if g != 1.0:
        progress(f"  峰值 {peak:.3f}，整体 {20*np.log10(g):+.2f} dB 防削波")
        o, a = o * g, a * g

    progress("编码…")
    write_wav(os.path.join(tmp, "original.wav"), o)
    write_wav(os.path.join(tmp, "instrumental.wav"), a)
    encode_m4a(os.path.join(tmp, "original.wav"), os.path.join(pack, "original.m4a"))
    encode_m4a(os.path.join(tmp, "instrumental.wav"), os.path.join(pack, "instrumental.m4a"))
    for f in os.listdir(tmp):
        os.remove(os.path.join(tmp, f))
    os.rmdir(tmp)

    meta = {
        "name": name,
        "duration": round(n / SR, 3),
        "sampleRate": SR,
        "note": note,
        "source": f"{os.path.basename(original)} + {os.path.basename(accomp)}",
        "alignedLagMs": round(lag / SR * 1000, 1),
        "alignCorr": round(corr, 4),
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "stems": ["original", "instrumental"],
    }
    with open(os.path.join(pack, "song.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    progress(f"完成：{pack}  时长 {n/SR/60:.2f} 分钟")
    return pack


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("original")
    ap.add_argument("accompaniment")
    ap.add_argument("outdir")
    ap.add_argument("--name", required=True)
    ap.add_argument("--note", default="")
    ap.add_argument("--no-align", action="store_true")
    a = ap.parse_args()
    build_pair(a.original, a.accompaniment, a.outdir, a.name,
               a.note, not a.no_align)

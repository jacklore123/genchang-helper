"""
MDX-Net 人声/伴奏分离引擎 —— 纯 numpy + onnxruntime 实现。

不依赖 torch / librosa / scipy，便于打包成小体积可执行文件。
算法与 UVR / python-audio-separator 的 MDX 路径逐行对齐：
    hop_length = 1024, segment_size = dim_t = 256, overlap = 0.25
    STFT: hann(periodic), center=True(reflect), 取前 dim_f 个频点,
          通道排布 [ch0.real, ch0.imag, ch1.real, ch1.imag]
    归一化: 峰值压到 0.9 送入模型, 输出再乘回原始峰值
"""

from __future__ import annotations

import os

import numpy as np
import onnxruntime as ort

HOP_LENGTH = 1024
SEGMENT_SIZE = 256
OVERLAP = 0.25
NORM_PEAK = 0.9

# UVR 官方 model_data 参数表（键 = 文件末尾 10,240,000 字节的 MD5，与 UVR/audio-separator 一致）
UVR_HASH_BYTES = 10000 * 1024
MODEL_REGISTRY: dict[str, dict] = {
    "55657dd70583b0fedfba5f67df11d711": {   # UVR-MDX-NET-Inst_HQ_3.onnx
        "name": "UVR-MDX-NET Inst HQ 3",
        "n_fft": 6144, "dim_f": 3072, "dim_t": 256,
        "compensate": 1.022, "primary": "instrumental",
    },
    "cb790d0c913647ced70fc6b38f5bea1a": {   # UVR-MDX-NET-Inst_HQ_5.onnx
        "name": "UVR-MDX-NET Inst HQ 5",
        "n_fft": 5120, "dim_f": 2560, "dim_t": 256,
        "compensate": 1.01, "primary": "instrumental",
    },
    "53c4baf4d12c3e6c3831bb8f5b532b93": {   # UVR_MDXNET_Main.onnx
        "name": "UVR_MDXNET_Main",
        "n_fft": 7680, "dim_f": 3072, "dim_t": 256,
        "compensate": 1.043, "primary": "vocals",
    },
}


def uvr_model_hash(path: str) -> str:
    import hashlib, io, os
    n = os.path.getsize(path)
    with open(path, "rb") as f:
        if n >= UVR_HASH_BYTES:
            f.seek(n - UVR_HASH_BYTES, io.SEEK_SET)
        return hashlib.md5(f.read()).hexdigest()


def auto_params(model_path: str, dim_f: int | None = None) -> dict:
    """按 UVR 哈希自动取模型参数；不认识时按 dim_f 推断。"""
    h = uvr_model_hash(model_path)
    if h in MODEL_REGISTRY:
        return dict(MODEL_REGISTRY[h])
    if dim_f is None:
        so = ort.SessionOptions()
        so.log_severity_level = 3
        s = ort.InferenceSession(model_path, sess_options=so, providers=["CPUExecutionProvider"])
        dim_f = int(s.get_inputs()[0].shape[2])
    return {"name": os.path.basename(model_path), "n_fft": pick_n_fft(model_path, dim_f),
            "dim_f": dim_f, "dim_t": SEGMENT_SIZE, "compensate": 1.035,
            "primary": "instrumental"}


# --------------------------------------------------------------------------- #
# STFT / iSTFT
# --------------------------------------------------------------------------- #
def _hann_periodic(n: int) -> np.ndarray:
    return (0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(n) / n)).astype(np.float32)


def stft(x: np.ndarray, n_fft: int, hop: int, window: np.ndarray) -> np.ndarray:
    """x: (C, N) float32 -> complex spec (C, n_bins, T). 等价 torch.stft(center=True, reflect)."""
    pad = n_fft // 2
    xp = np.pad(x, ((0, 0), (pad, pad)), mode="reflect")
    n = xp.shape[-1]
    if n < n_fft:
        xp = np.pad(xp, ((0, 0), (0, n_fft - n)), mode="constant")
        n = xp.shape[-1]
    T = 1 + (n - n_fft) // hop
    frames = np.lib.stride_tricks.sliding_window_view(xp, n_fft, axis=-1)[:, ::hop, :][:, :T, :]
    frames = frames * window
    spec = np.fft.rfft(frames, n=n_fft, axis=-1)          # (C, T, n_bins)
    return np.ascontiguousarray(spec.transpose(0, 2, 1))  # (C, n_bins, T)


def istft(spec: np.ndarray, n_fft: int, hop: int, window: np.ndarray, length: int | None = None) -> np.ndarray:
    """spec: (C, n_bins, T) complex -> (C, samples). 等价 torch.istft(center=True)."""
    C, _, T = spec.shape
    frames = np.fft.irfft(spec.transpose(0, 2, 1), n=n_fft, axis=-1).astype(np.float32)  # (C, T, n_fft)
    frames = frames * window
    out_len = n_fft + (T - 1) * hop
    out = np.zeros((C, out_len), dtype=np.float32)
    wsum = np.zeros(out_len, dtype=np.float32)
    w2 = (window.astype(np.float64) ** 2)
    idx = np.arange(n_fft)
    for i in range(T):
        s = i * hop
        out[:, s:s + n_fft] += frames[:, i]
        wsum[s:s + n_fft] += w2
    out /= np.maximum(wsum, 1e-8).astype(np.float32)
    trim = n_fft // 2
    out = out[:, trim:out_len - trim]
    if length is not None:
        if out.shape[-1] < length:
            out = np.pad(out, ((0, 0), (0, length - out.shape[-1])))
        out = out[:, :length]
    return out


def _spec_to_model_input(spec: np.ndarray, dim_f: int) -> np.ndarray:
    """(C=2, n_bins, T) complex -> (1, 4, dim_f, T) float32"""
    s = spec[:, :dim_f, :]
    re = s.real.astype(np.float32)
    im = s.imag.astype(np.float32)
    out = np.empty((1, 4, dim_f, s.shape[-1]), dtype=np.float32)
    out[0, 0] = re[0]
    out[0, 1] = im[0]
    out[0, 2] = re[1]
    out[0, 3] = im[1]
    return out


def _model_output_to_spec(out: np.ndarray, n_bins: int) -> np.ndarray:
    """(1, 4, dim_f, T) float32 -> (2, n_bins, T) complex"""
    o = out[0]  # (4, dim_f, T)
    dim_f = o.shape[1]
    T = o.shape[2]
    spec = np.zeros((2, n_bins, T), dtype=np.complex64)
    spec[0, :dim_f] = o[0] + 1j * o[1]
    spec[1, :dim_f] = o[2] + 1j * o[3]
    return spec


# --------------------------------------------------------------------------- #
# 分离器
# --------------------------------------------------------------------------- #
class MDXSeparator:
    def __init__(
        self,
        model_path: str,
        n_fft: int = 7680,
        dim_f: int | None = None,
        dim_t: int = SEGMENT_SIZE,
        hop: int = HOP_LENGTH,
        overlap: float = OVERLAP,
        compensate: float = 1.035,
        primary: str = "instrumental",
        providers=None,
        num_threads: int | None = None,
        progress=None,
    ):
        self.model_path = model_path
        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        if num_threads:
            so.intra_op_num_threads = num_threads
        if providers is None:
            avail = ort.get_available_providers()
            providers = [p for p in ("DmlExecutionProvider", "CPUExecutionProvider") if p in avail]
        self.session = ort.InferenceSession(model_path, sess_options=so, providers=providers)
        self.providers = self.session.get_providers()

        shape = self.session.get_inputs()[0].shape
        if dim_f is None:
            dim_f = int(shape[2])
        self.dim_f = dim_f
        self.dim_t = int(shape[3]) if isinstance(shape[3], int) else dim_t
        self.n_fft = n_fft
        self.n_bins = n_fft // 2 + 1
        if self.dim_f > self.n_bins:
            raise ValueError(f"dim_f={self.dim_f} 超过 n_bins={self.n_bins}，n_fft 选错了")
        self.hop = hop
        self.overlap = overlap
        self.compensate = compensate
        self.primary = primary
        self.window = _hann_periodic(n_fft)
        self.trim = n_fft // 2
        self.chunk_size = hop * (self.dim_t - 1)
        self.gen_size = self.chunk_size - 2 * self.trim
        self.progress = progress
        self.input_name = self.session.get_inputs()[0].name

    # -- 单段推理：chunk (2, chunk_size) -> (2, chunk_size) ------------------ #
    def _run_chunk(self, chunk: np.ndarray) -> np.ndarray:
        spec = stft(chunk, self.n_fft, self.hop, self.window)
        spec[:, :3, :] = 0.0                      # UVR 固定操作：清掉最低 3 个频点
        inp = _spec_to_model_input(spec, self.dim_f)
        out = self.session.run(None, {self.input_name: inp})[0]
        full = _model_output_to_spec(out, self.n_bins)
        return istft(full, self.n_fft, self.hop, self.window, length=self.chunk_size)

    # -- 整轨推理 ----------------------------------------------------------- #
    def separate(self, mix: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """mix: (2, N) float32 -> (instrumental, vocals)，长度均为 N。"""
        assert mix.ndim == 2 and mix.shape[0] == 2, "需要 (2, N) 立体声"
        mix = np.ascontiguousarray(mix, dtype=np.float32)
        n_sample = mix.shape[-1]

        peak = float(np.abs(mix).max())
        scale = (NORM_PEAK / peak) if peak > NORM_PEAK else 1.0
        mix_n = mix * scale if scale != 1.0 else mix

        chunk_size = self.chunk_size
        trim = self.trim
        gen_size = self.gen_size
        pad = gen_size + trim - (n_sample % gen_size)
        mixture = np.concatenate(
            (np.zeros((2, trim), np.float32), mix_n, np.zeros((2, pad), np.float32)), axis=1
        )
        L = mixture.shape[-1]
        step = max(1, int((1.0 - self.overlap) * chunk_size))

        result = np.zeros((2, L), np.float32)
        divider = np.zeros((2, L), np.float32)

        starts = list(range(0, L, step))
        for k, i in enumerate(starts):
            end = min(i + chunk_size, L)
            actual = end - i
            part = mixture[:, i:end]
            if end != i + chunk_size:
                part = np.concatenate((part, np.zeros((2, i + chunk_size - end), np.float32)), axis=1)
            est = self._run_chunk(part)
            if self.overlap != 0:
                w = _hann_periodic(actual)
                est[:, :actual] *= w
                divider[:, i:end] += w
            else:
                divider[:, i:end] += 1.0
            result[:, i:end] += est[:, :actual]
            if self.progress:
                self.progress(k + 1, len(starts))

        tar = result / np.maximum(divider, 1e-8)
        tar = tar[:, trim:tar.shape[-1] - trim]
        if tar.shape[-1] < n_sample:
            tar = np.pad(tar, ((0, 0), (0, n_sample - tar.shape[-1])))
        primary = tar[:, :n_sample] / scale
        if self.primary == "vocals":
            vocals = primary
            instrumental = mix - vocals * self.compensate
        else:
            instrumental = primary
            vocals = mix - instrumental * self.compensate
        return instrumental.astype(np.float32), vocals.astype(np.float32)


def pick_n_fft(model_path: str, dim_f: int) -> int:
    """按 dim_f 推断 MDX 模型的 n_fft（UVR 常见取值）。"""
    cands = [5120, 6144, 7680, 8192, 4096, 16384]
    ok = [c for c in cands if c // 2 + 1 >= dim_f]
    if not ok:
        return (dim_f - 1) * 2
    # UVR 的 dim_f=3072 模型绝大多数是 n_fft=7680；dim_f=2048 多为 5120/6144
    pref = {3072: [7680, 6144], 2048: [5120, 6144], 2560: [5120], 1024: [4096]}
    for p in pref.get(dim_f, []):
        if p in ok:
            return p
    return min(ok)

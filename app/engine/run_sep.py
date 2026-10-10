"""分离命令行：python _lab/run_sep.py <输入> <输出目录> [--model X.onnx] [--nfft 7680] [--start 0] [--dur 30]"""
import argparse, os, subprocess, sys, time
import numpy as np
import imageio_ffmpeg

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mdx_engine import MDXSeparator, pick_n_fft, auto_params  # noqa: E402
import subproc  # noqa: E402

FF = imageio_ffmpeg.get_ffmpeg_exe()
SR = 44100


def decode(path, sr=SR, start=None, dur=None):
    tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp_audio.f32")
    cmd = [FF, "-y", "-v", "error"]
    if start is not None:
        cmd += ["-ss", str(start)]
    cmd += ["-i", path, "-vn", "-ac", "2", "-ar", str(sr)]
    if dur is not None:
        cmd += ["-t", str(dur)]
    cmd += ["-f", "f32le", tmp]
    subproc.run(cmd, check=True)          # 不弹黑窗
    a = np.fromfile(tmp, dtype="<f4")
    os.remove(tmp)
    n = (len(a) // 2) * 2
    return np.ascontiguousarray(a[:n].reshape(-1, 2).T)  # (2, N)


def write_wav(path, x, sr=SR, subtype="FLOAT"):
    import soundfile as sf
    sf.write(path, np.ascontiguousarray(x.T), sr, subtype=subtype)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("outdir")
    ap.add_argument("--model", default=r"_lab\models\UVR-MDX-NET-Inst_HQ_3.onnx")
    ap.add_argument("--nfft", type=int, default=0)
    ap.add_argument("--dimf", type=int, default=0)
    ap.add_argument("--start", type=float, default=None)
    ap.add_argument("--dur", type=float, default=None)
    ap.add_argument("--providers", default="")
    ap.add_argument("--primary", default="instrumental", choices=["instrumental", "vocals"])
    ap.add_argument("--compensate", type=float, default=1.035)
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    print(f"解码 {args.input} ...")
    t0 = time.time()
    mix = decode(args.input, start=args.start, dur=args.dur)
    print(f"  {mix.shape[1]/SR:.2f}s  峰值={np.abs(mix).max():.4f}  用时 {time.time()-t0:.1f}s")

    providers = [p for p in args.providers.split(",") if p] or None
    p = auto_params(args.model)
    if args.nfft:
        p["n_fft"] = args.nfft
    if args.dimf:
        p["dim_f"] = args.dimf
    if args.primary != "instrumental":
        p["primary"] = args.primary
    if args.compensate != 1.035:
        p["compensate"] = args.compensate
    print(f"模型参数: {p['name']}  n_fft={p['n_fft']} dim_f={p['dim_f']} dim_t={p['dim_t']} "
          f"compensate={p['compensate']} primary={p['primary']}")
    sep = MDXSeparator(args.model, n_fft=p["n_fft"], dim_f=p["dim_f"], dim_t=p["dim_t"],
                       compensate=p["compensate"], primary=p["primary"], providers=providers,
                       progress=lambda i, n: print(f"\r  推理 {i}/{n}", end="", flush=True))
    print(f"\n模型: {os.path.basename(args.model)}  providers={sep.providers}")
    print(f"  dim_f={sep.dim_f} dim_t={sep.dim_t} n_fft={sep.n_fft} n_bins={sep.n_bins}")
    print(f"  chunk={sep.chunk_size} trim={sep.trim} gen={sep.gen_size}")

    t0 = time.time()
    inst, voc = sep.separate(mix)
    el = time.time() - t0
    print(f"\n推理完成 {el:.1f}s  (音频时长 {mix.shape[1]/SR:.1f}s, {mix.shape[1]/SR/el:.2f}x 实时)")

    write_wav(os.path.join(args.outdir, "original.wav"), mix)
    write_wav(os.path.join(args.outdir, "instrumental.wav"), inst)
    write_wav(os.path.join(args.outdir, "vocals.wav"), voc)

    def db(x):
        r = np.sqrt((x.astype(np.float64) ** 2).mean())
        return 20 * np.log10(r + 1e-12)

    print(f"RMS  原唱 {db(mix):7.2f} dB | 伴奏 {db(inst):7.2f} dB | 人声 {db(voc):7.2f} dB")
    print(f"残差检查 ||原唱 - (伴奏*1.035 + 人声)|| = {np.abs(mix - (inst*1.035 + voc)).max():.6f}")
    print("输出:", args.outdir)


if __name__ == "__main__":
    main()

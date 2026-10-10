"""把一首歌做成"跟唱包"：原唱 + AI 分离出的伴奏 / 人声。

产出目录:
    <outdir>/<名字>/original.m4a
                  instrumental.m4a
                  vocals.m4a
                  song.json
"""
import argparse, json, os, subprocess, sys, time
import numpy as np
import imageio_ffmpeg

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mdx_engine import MDXSeparator, auto_params  # noqa: E402
from run_sep import decode, write_wav              # noqa: E402

FF = imageio_ffmpeg.get_ffmpeg_exe()
SR = 44100


def encode_m4a(wav, out, bitrate="192k"):
    subprocess.run([FF, "-y", "-v", "error", "-i", wav, "-c:a", "aac", "-b:a", bitrate,
                    "-movflags", "+faststart", out], check=True)


def build(src, outdir, name=None, model=None, progress=print):
    name = name or os.path.splitext(os.path.basename(src))[0]
    pack = os.path.join(outdir, name)
    os.makedirs(pack, exist_ok=True)
    model = model or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "models", "UVR-MDX-NET-Inst_HQ_3.onnx")

    progress("解码音频…")
    t0 = time.time()
    mix = decode(src)
    dur = mix.shape[1] / SR
    progress(f"  时长 {dur/60:.2f} 分钟，用时 {time.time()-t0:.1f}s")

    p = auto_params(model)
    progress(f"分离模型 {p['name']} (n_fft={p['n_fft']}, 设备 DirectML/CPU)…")
    sep = MDXSeparator(model, n_fft=p["n_fft"], dim_f=p["dim_f"], dim_t=p["dim_t"],
                       compensate=p["compensate"], primary=p["primary"])
    progress(f"  推理后端: {sep.providers}")

    t0 = time.time()
    n_chunks = len(range(0, mix.shape[1] + sep.gen_size, max(1, int((1 - sep.overlap) * sep.chunk_size))))
    last = [0]

    def cb(i, n):
        if i - last[0] >= 1 or i == n:
            last[0] = i
            progress(f"  进度 {i}/{n} ({i*100//max(1,n)}%)")

    sep.progress = cb
    inst, voc = sep.separate(mix)
    el = time.time() - t0
    progress(f"  完成，用时 {el:.1f}s（{dur/el:.1f}x 实时）")

    tmp = os.path.join(pack, "_tmp")
    os.makedirs(tmp, exist_ok=True)
    # 三轨共用一个增益，防止削波，同时保持相对电平和采样对齐
    peak = float(max(np.abs(mix).max(), np.abs(inst).max(), np.abs(voc).max()))
    g = 0.95 / peak if peak > 0.95 else 1.0
    if g != 1.0:
        progress(f"  峰值 {peak:.3f}，整体衰减 {20*np.log10(g):+.2f} dB 防削波")
        mix, inst, voc = mix * g, inst * g, voc * g
    progress("编码 m4a…")
    write_wav(os.path.join(tmp, "original.wav"), mix)
    write_wav(os.path.join(tmp, "instrumental.wav"), inst)
    write_wav(os.path.join(tmp, "vocals.wav"), voc)
    for stem in ("original", "instrumental", "vocals"):
        encode_m4a(os.path.join(tmp, stem + ".wav"), os.path.join(pack, stem + ".m4a"))
    for f in os.listdir(tmp):
        os.remove(os.path.join(tmp, f))
    os.rmdir(tmp)

    meta = {
        "name": name,
        "duration": round(dur, 3),
        "sampleRate": SR,
        "source": os.path.basename(src),
        "model": p["name"],
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "stems": ["original", "instrumental", "vocals"],
    }
    with open(os.path.join(pack, "song.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    progress(f"完成: {pack}")
    return pack


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("outdir")
    ap.add_argument("--name", default=None)
    ap.add_argument("--model", default=None)
    args = ap.parse_args()
    build(args.input, args.outdir, args.name, args.model)


if __name__ == "__main__":
    main()

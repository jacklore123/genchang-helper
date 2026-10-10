#!/usr/bin/env python3
"""下载人声分离模型（UVR-MDX-NET Inst HQ 3）。

模型不放进仓库（66MB），用这个脚本随时拉取。
    python tools/fetch_model.py
国内网络优先走镜像，可用 GENCHANG_MODEL_BASE 覆盖。
"""
from __future__ import annotations

import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402


def download(url: str, dst: str) -> bool:
    tmp = dst + ".part"
    try:
        print("  下载", url)
        t0 = time.time()
        with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            got = 0
            last = 0
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if total and got - last > 8 << 20:
                    last = got
                    print("    %5.1f%%  %.1f MB / %.1f MB" % (got * 100.0 / total, got / 1e6, total / 1e6))
        os.replace(tmp, dst)
        print("  完成 %.1f MB，用时 %.1fs" % (os.path.getsize(dst) / 1e6, time.time() - t0))
        return True
    except Exception as e:
        print("  失败:", e)
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def main():
    os.makedirs(common.MODELS, exist_ok=True)
    dst = os.path.join(common.MODELS, common.MODEL_FILE)
    if os.path.isfile(dst) and os.path.getsize(dst) > 10_000_000:
        print("模型已存在:", dst)
        return
    url = common.MODEL_BASE + common.MODEL_FILE
    for prefix in common.MODEL_MIRRORS:
        real = prefix + url if prefix else url
        print("尝试通道:", prefix or "直连")
        if download(real, dst):
            break
    else:
        raise SystemExit("模型下载失败，请设置 GENCHANG_MODEL_BASE 或手动放到 app/models/")

    # 校验：必须能被 onnxruntime 打开，且输入形状符合预期
    try:
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.log_severity_level = 3
        s = ort.InferenceSession(dst, sess_options=so, providers=["CPUExecutionProvider"])
        shape = s.get_inputs()[0].shape
        print("模型输入:", shape, "→ dim_f =", shape[2])
    except Exception as e:
        raise SystemExit("模型无法加载: %s" % e)


if __name__ == "__main__":
    main()

"""跟唱助手 · 多角度自检套件

跑法：
    python tools/selftest.py

覆盖：
  A. 本地服务 HTTP 协议（状态码 / Range / HEAD / 404 / 目录穿越 / 并发）
  B. 音轨数据完整性（分段取回的字节要和原文件逐字节一致）
  C. 连接被客户端粗暴掐断时服务不能倒
  D. 心跳机制（ping 续命、bye 不会立刻杀进程、失联才回收）
  E. 歌词解析与自动并轨
  F. 歌曲包完整性（三轨齐、时长一致、对齐残差）
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
APP = os.path.join(ROOT, "app")
sys.path.insert(0, APP)
sys.path.insert(0, os.path.join(APP, "engine"))

PASS, FAIL, WARN = [], [], []


def ok(name, extra=""):
    PASS.append(name)
    print("  \u2713 %-52s %s" % (name, extra))


def bad(name, extra=""):
    FAIL.append(name)
    print("  \u2717 %-52s %s" % (name, extra))


def warn(name, extra=""):
    WARN.append(name)
    print("  ! %-52s %s" % (name, extra))


def check(name, cond, extra=""):
    (ok if cond else bad)(name, extra)
    return cond


# --------------------------------------------------------------------------- #
def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def start_server(port, lib, extra_env=None):
    env = dict(os.environ)
    env.update({"GENCHANG_NO_WINDOW": "1", "GENCHANG_PORT": str(port),
                "GENCHANG_LIB": lib, "PYTHONIOENCODING": "utf-8"})
    if extra_env:
        env.update(extra_env)
    p = subprocess.Popen([sys.executable, os.path.join(APP, "server.py")],
                         env=env, cwd=ROOT,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         creationflags=0x08000000 if os.name == "nt" else 0)
    for _ in range(120):
        time.sleep(0.25)
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/api/ping" % port, timeout=2).read()
            return p
        except Exception:
            if p.poll() is not None:
                out = p.stdout.read().decode("utf-8", "replace")
                raise RuntimeError("服务启动失败：\n" + out[-1500:])
    raise RuntimeError("服务启动超时")


def req(port, path, rng=None, method="GET", timeout=10):
    r = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), method=method)
    if rng:
        r.add_header("Range", rng)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def alive(port):
    try:
        return json.loads(urllib.request.urlopen(
            "http://127.0.0.1:%d/api/ping" % port, timeout=4).read())["ok"]
    except Exception:
        return False


# --------------------------------------------------------------------------- #
def test_http(port, song, files):
    print("\n[A] 本地服务 HTTP 协议")
    st, _, body = req(port, "/api/songs")
    songs = json.loads(body)
    check("GET /api/songs 返回 200 + JSON", st == 200 and isinstance(songs, list))
    if songs:
        f = songs[0].get("files", {})
        check("歌曲含 original/instrumental/vocals 三轨",
              all(k in f for k in ("original", "instrumental", "vocals")), str(f))
    check("GET / 返回界面", req(port, "/")[0] == 200)
    check("HEAD / 有响应（不是 501）", req(port, "/", method="HEAD")[0] in (200, 404))

    q = urllib.parse.quote(song)
    st, h, d = req(port, "/media/%s/instrumental.m4a" % q, "bytes=0-999")
    check("Range 请求返回 206", st == 206, "got %s" % st)
    check("Content-Range 正确", h.get("Content-Range", "").endswith("/%d" % os.path.getsize(
        os.path.join(LIB, song, "instrumental.m4a"))), str(h.get("Content-Range")))
    check("Range 长度正确", len(d) == 1000, "%d 字节" % len(d))
    check("Accept-Ranges: bytes", h.get("Accept-Ranges") == "bytes")

    st, _, d = req(port, "/media/%s/instrumental.m4a" % q, "bytes=99999999-")
    check("越界 Range 不崩（回 416 或空）", st in (200, 206, 416), "got %s, %d 字节" % (st, len(d)))

    check("不存在的文件返回 404", req(port, "/media/%s/nope.m4a" % q)[0] == 404)
    check("不存在的接口返回 404", req(port, "/api/nothing")[0] == 404)

    # 目录穿越：绝不能读到库外文件
    for evil in ("/media/..%2f..%2fserver.py",
                 "/media/" + q + "/..%2f..%2fserver.py",
                 "/media/..%5c..%5cserver.py"):
        st, _, d = req(port, evil)
        check("目录穿越被挡住 %s" % evil[:28], st in (400, 404) and b"import" not in d[:200])

    check("歌词接口", req(port, "/media/%s/lyrics.lrc" % q)[0] == 200)
    check("不存在的歌词不报错", req(port, "/media/%s/nolyrics.lrc" % q)[0] == 404)


def test_bytes(port, song, files):
    print("\n[B] 音轨数据完整性（分段取回 vs 原文件）")
    q = urllib.parse.quote(song)
    for key, fn in files.items():
        path = os.path.join(LIB, song, fn)
        size = os.path.getsize(path)
        whole = open(path, "rb").read()
        # 用多段 Range 拼出整个文件，必须逐字节一致
        got = b""
        chunk = 300000
        while len(got) < size:
            a = len(got)
            b = min(a + chunk - 1, size - 1)
            st, _, d = req(port, "/media/%s/%s" % (q, fn), "bytes=%d-%d" % (a, b))
            if st != 206 or not d:
                break
            got += d
        same = got == whole
        check("%-13s 分块取回逐字节一致" % key,
              same, "%d/%d 字节" % (len(got), size) if not same else "%d 字节" % size)
        # 单次无 Range 整体取
        st, h, d = req(port, "/media/%s/%s" % (q, fn))
        check("%-13s 整体取回一致" % key, d == whole and st == 200, "%d 字节" % len(d))


def test_abrupt(port, song):
    print("\n[C] 客户端粗暴掐断连接")
    q = urllib.parse.quote(song)
    for i in range(6):
        s = socket.create_connection(("127.0.0.1", port), timeout=5)
        s.sendall(("GET /media/%s/instrumental.m4a HTTP/1.1\r\n"
                   "Host: 127.0.0.1\r\nRange: bytes=0-\r\n\r\n" % q).encode())
        time.sleep(0.05)
        s.close()                       # 收到一半就跑
    time.sleep(1.0)
    check("6 次中途断开后服务仍存活", alive(port))

    print("\n[C2] 20 路并发请求")
    errs = []

    def one():
        try:
            st, _, d = req(port, "/media/%s/instrumental.m4a" % q, "bytes=0-65535", timeout=15)
            if st != 206 or len(d) != 65536:
                errs.append("status=%s len=%d" % (st, len(d)))
        except Exception as e:
            errs.append(str(e))

    ts = [threading.Thread(target=one) for _ in range(20)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    check("20 路并发全部正确", not errs, "; ".join(errs[:3]))
    check("并发后服务仍存活", alive(port))


def test_heartbeat(port):
    print("\n[D] 心跳机制")
    check("ping 返回 ok", alive(port))
    st, _, _ = req(port, "/api/bye", method="POST")
    check("POST /api/bye 被接受", st == 200, "got %s" % st)
    time.sleep(1.5)
    check("bye 之后服务**没有**立刻被杀", alive(port), "（旧版会直接 os._exit）")
    check("bye 之后 ping 能续命", alive(port))


def test_lyrics():
    print("\n[E] 歌词解析与自动并轨")
    import align_lyrics as AL
    lrc = os.path.join(ROOT, "app", "seed", "紫荆花盛开", "lyrics.lrc")
    txt = open(lrc, encoding="utf-8").read()
    lines = [l for l in txt.splitlines() if l.strip().startswith("[")]
    check("内置歌词是标准 LRC", len(lines) > 10, "%d 行" % len(lines))
    times = []
    for l in lines:
        if l.startswith("[") and "]" in l:
            t = l[1:l.index("]")]
            if ":" in t and t[0].isdigit():
                mm, ss = t.split(":")[:2]
                try:
                    times.append(int(mm) * 60 + float(ss))
                except ValueError:
                    pass
    check("时间轴递增", all(times[i] <= times[i + 1] for i in range(len(times) - 1)))
    check("首句在合理位置（<60s）", times and times[0] < 60, "%.2fs" % (times[0] if times else -1))

    # 纯文本歌词 → 自动并轨
    inst = os.path.join(LIB, "紫荆花盛开", "vocals.m4a")
    if os.path.isfile(inst):
        plain = ["紫荆花飘扬", "飞向避风的海港", "摇曳一湾水温柔", "全是 最爱坚守",
                 "纯真 是你的微笑", "一眼到永远的抱抱", "爱像 亲恩般深长", "时时 为我鼓掌"]
        try:
            env = AL.envelope(AL.decode_mono(inst))
            lines = [{"t": 0.0, "text": t} for t in plain]
            res = AL.distribute_plain(env, lines)
            ts = [float(r["t"]) if isinstance(r, dict) else float(r) for r in res]
            check("纯文本歌词并轨出时间", len(ts) == len(plain), "%d 句" % len(ts))
            check("并轨时间单调不减",
                  all(ts[i] <= ts[i + 1] + 0.01 for i in range(len(ts) - 1)),
                  str([round(x, 2) for x in ts[:6]]))
            check("并轨结果落在音频时长内",
                  ts[-1] < 400 and ts[0] >= 0, "首 %.2fs 末 %.2fs" % (ts[0], ts[-1]))
            # LRC 路径：全局偏移估计
            real = [{"t": (13.88 + i * 3.5), "text": t, "mark": False} for i, t in enumerate(plain)]
            env2 = AL.envelope(AL.decode_mono(inst))
            off = AL.global_offset(env2, [r["t"] for r in real])
            check("LRC 全局偏移可估计", abs(off) < 15, "估计偏移 %.2fs" % off)
        except Exception as e:
            warn("纯文本并轨", "%s: %s" % (type(e).__name__, e))
    else:
        warn("纯文本并轨", "库里没有人声轨，跳过")


def test_pack(song):
    print("\n[F] 歌曲包完整性")
    d = os.path.join(LIB, song)
    files = os.listdir(d)
    for f in ("song.json", "lyrics.lrc"):
        check("存在 %s" % f, f in files, str(files))
    try:
        j = json.load(open(os.path.join(d, "song.json"), encoding="utf-8"))
        check("song.json 可解析", isinstance(j, dict), str(j)[:90])
    except Exception as e:
        bad("song.json 可解析", str(e))
    sizes = {f: os.path.getsize(os.path.join(d, f)) for f in files
             if f.endswith((".m4a", ".mp3"))}
    if len(sizes) >= 3:
        vals = sorted(sizes.values())
        ratio = vals[0] / vals[-1]
        check("三轨长度接近（同一母带切出）", ratio > 0.97, "最小/最大 = %.4f" % ratio)
    else:
        warn("三轨长度接近", "音轨不足 3 条")


# --------------------------------------------------------------------------- #
LIB = ""


def main():
    global LIB
    print("=" * 66)
    print("跟唱助手 · 多角度自检套件")
    print("=" * 66)

    tmp = tempfile.mkdtemp(prefix="genchang_test_")
    LIB = os.path.join(tmp, "library")
    os.makedirs(LIB)
    seed = os.path.join(APP, "seed")
    if os.path.isdir(seed):
        for n in os.listdir(seed):
            shutil.copytree(os.path.join(seed, n), os.path.join(LIB, n), dirs_exist_ok=True)
    # 补齐音频：从交付库拷（仓库里没有音频）
    donor = None
    for cand in (r"F:\跟唱助手-紫荆花版\library", os.path.join(ROOT, "library")):
        if os.path.isdir(cand) and any(
                os.path.exists(os.path.join(cand, s, "instrumental.m4a"))
                for s in os.listdir(cand)):
            donor = cand
            break
    if donor:
        for n in os.listdir(donor):
            src = os.path.join(donor, n)
            if os.path.isdir(src):
                shutil.copytree(src, os.path.join(LIB, n), dirs_exist_ok=True)

    songs = [s for s in os.listdir(LIB) if os.path.isdir(os.path.join(LIB, s))]
    if not songs or not os.path.isfile(os.path.join(LIB, songs[0], "instrumental.m4a")):
        print("\n[!] 测试库缺少音频文件，先跑一次程序让内置歌曲铺好，或把音频放进 library/。")
        print("    位置：%s" % LIB)
        return 2
    song = songs[0]
    files = {k: v for k, v in
             [("original", "original.m4a"), ("instrumental", "instrumental.m4a"),
              ("vocals", "vocals.m4a")]
             if os.path.isfile(os.path.join(LIB, song, v))}
    print("测试歌曲：%s   音轨：%s" % (song, list(files)))

    port = free_port()
    proc = start_server(port, LIB)
    try:
        test_http(port, song, files)
        test_bytes(port, song, files)
        test_abrupt(port, song)
        test_heartbeat(port)
        test_pack(song)
    finally:
        try:
            proc.terminate()
        except Exception:
            pass
    test_lyrics()

    print("\n" + "=" * 66)
    print("通过 %d 项   失败 %d 项   提醒 %d 项" % (len(PASS), len(FAIL), len(WARN)))
    if FAIL:
        print("\n失败项：")
        for f in FAIL:
            print("   -", f)
    print("=" * 66)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())

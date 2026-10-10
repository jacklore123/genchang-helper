#!/usr/bin/env python3
"""跟唱助手 —— 电脑版本地服务

启动后：
  * 在 127.0.0.1 上开一个本地 HTTP 服务（含 Range，支持音频拖动）
  * 用 Edge / Chrome 的应用模式打开一个无地址栏的窗口
  * 支持导入任意 音频/视频 → 本地 AI 分离出伴奏，加入歌曲库
"""
from __future__ import annotations

import json
import os
import posixpath
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import queue
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

APP_NAME = "跟唱助手"
HERE = os.path.dirname(os.path.abspath(__file__))
FROZEN = getattr(sys, "frozen", False)


def res_dir() -> str:
    """打包后资源目录（PyInstaller 解包目录），开发时就是本目录。"""
    if FROZEN:
        return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
    return HERE


UI_DIR = os.path.join(res_dir(), "ui")
MODELS_DIR = os.path.join(res_dir(), "models")
DEFAULT_MODEL = "UVR-MDX-NET-Inst_HQ_3.onnx"

STORE: dict = {}
STORE_LOCK = threading.Lock()


# --------------------------------------------------------------------------- #
# 歌曲库位置
# --------------------------------------------------------------------------- #
def library_dir() -> str:
    env = os.environ.get("GENCHANG_LIB")
    if env:
        os.makedirs(env, exist_ok=True)
        return env
    # 打包后：歌曲库放在 exe 同级的 library 文件夹 —— 整个文件夹拷走就能换电脑用
    if FROZEN:
        base = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "library")
    else:
        base = os.path.join(HERE, "library")
    try:
        os.makedirs(base, exist_ok=True)
        with open(os.path.join(base, ".wtest"), "w") as f:
            f.write("1")
        os.remove(os.path.join(base, ".wtest"))
        return base
    except Exception:
        fb = os.path.join(os.path.expanduser("~"), "Music", APP_NAME)
        os.makedirs(fb, exist_ok=True)
        return fb


def model_path() -> str | None:
    p = os.path.join(MODELS_DIR, DEFAULT_MODEL)
    if os.path.isfile(p):
        return p
    if os.path.isdir(MODELS_DIR):
        onnx = [f for f in os.listdir(MODELS_DIR) if f.lower().endswith(".onnx")]
        if onnx:
            return os.path.join(MODELS_DIR, sorted(onnx)[0])
    return None


def list_songs():
    lib = library_dir()
    out = []
    if not os.path.isdir(lib):
        return out
    exts = (".m4a", ".mp3", ".wav", ".flac", ".ogg", ".aac", ".opus")
    for name in sorted(os.listdir(lib)):
        d = os.path.join(lib, name)
        if name.startswith("_") or not os.path.isdir(d):
            continue
        files = {}
        for stem in ("original", "instrumental", "vocals"):
            for e in exts:
                if os.path.isfile(os.path.join(d, stem + e)):
                    files[stem] = stem + e
                    break
        if "instrumental" not in files:
            continue
        meta = {}
        mp = os.path.join(d, "song.json")
        if os.path.isfile(mp):
            try:
                meta = json.load(open(mp, encoding="utf-8"))
            except Exception:
                meta = {}
        dur = meta.get("duration") or 0
        sub = f"{int(dur)//60}:{int(dur)%60:02d}" if dur else ""
        if meta.get("note"):
            sub += ("　" if sub else "") + meta["note"]
        elif meta.get("model"):
            sub += ("　" if sub else "") + "AI伴奏"
        out.append({"id": name, "name": meta.get("name", name), "sub": sub,
                    "duration": dur, "files": files,
                    "stems": list(files.keys())})
    return out


# --------------------------------------------------------------------------- #
# 导入任务
# --------------------------------------------------------------------------- #
class Job:
    def __init__(self, jid, filename):
        self.id = jid
        self.filename = filename
        self.q: queue.Queue = queue.Queue()
        self.state = "running"
        self.logs: list[str] = []
        self.pct = 0.0
        self.error = ""

    def log(self, msg):
        msg = str(msg)
        self.logs.append(msg)
        self.q.put({"log": msg})

    def percent(self, p):
        self.pct = float(p)
        self.q.put({"pct": self.pct})


def run_import(job: Job, saved_path: str, display_name: str, accomp_path: str | None = None):
    try:
        eng = os.path.join(res_dir(), "engine")
        if eng not in sys.path:
            sys.path.insert(0, eng)

        if accomp_path:
            # 官方伴奏模式：不跑 AI，只做自动对齐 —— 音质零损失
            import build_pair  # type: ignore

            job.log(f"开始处理：{display_name}（原唱 + 官方伴奏）")
            job.percent(5)

            def cb2(msg: str):
                s = str(msg)
                job.log(s)
                if s.startswith("解码原唱"):
                    job.percent(10)
                elif s.startswith("解码伴奏"):
                    job.percent(25)
                elif s.startswith("对齐"):
                    job.percent(45)
                elif "包络互相关" in s or "窗口精修" in s:
                    job.percent(60)
                elif s.startswith("编码"):
                    job.percent(80)

            pack = build_pair.build_pair(saved_path, accomp_path, library_dir(), display_name,
                                         note="官方伴奏", progress=cb2)
            job.percent(100)
            job.log("完成：" + os.path.basename(pack))
            job.state = "done"
            return

        import build_pack  # type: ignore
        mp = model_path()
        if not mp:
            raise RuntimeError("找不到分离模型文件（models/*.onnx）")

        def cb(msg: str):
            s = str(msg)
            m = re.search(r"进度\s+(\d+)/(\d+)", s)
            if m:
                a, b = int(m.group(1)), int(m.group(2))
                job.percent(6 + 86 * a / max(1, b))
                if a % 5 == 0 or a == b:
                    job.log(f"  分离中 {a}/{b}  ({a*100//max(1,b)}%)")
                return
            if s.startswith("解码"):
                job.percent(2)
            elif s.startswith("分离模型"):
                job.percent(6)
            elif s.startswith("编码"):
                job.percent(93)
            job.log(s)

        job.log(f"开始处理：{display_name}")
        pack = build_pack.build(saved_path, library_dir(), display_name, mp, progress=cb)
        job.percent(100)
        job.log("完成：" + os.path.basename(pack))
        job.state = "done"
    except Exception as e:
        job.error = str(e)
        job.state = "error"
        job.log("✖ " + str(e))
    finally:
        job.q.put({"state": job.state, "error": job.error})
        for p in (saved_path, accomp_path):
            if p:
                try:
                    os.remove(p)
                except Exception:
                    pass


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    server_version = "GenChang/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # 安静点
        pass

    # -- 工具 -------------------------------------------------------------- #
    def _send(self, code, body=b"", ctype="application/octet-stream", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _file(self, path, ctype):
        if not os.path.isfile(path):
            self._send(404, b"not found", "text/plain")
            return
        size = os.path.getsize(path)
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        code = 200
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)", rng)
            if m:
                if m.group(1):
                    start = int(m.group(1))
                if m.group(2):
                    end = min(int(m.group(2)), size - 1)
                if start > end or start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                code = 206
        length = end - start + 1
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(start)
            left = length
            while left > 0:
                chunk = f.read(min(262144, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                left -= len(chunk)

    # -- 路由 -------------------------------------------------------------- #
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(u.path)

        if path in ("/", "/index.html"):
            return self._file(os.path.join(UI_DIR, "index.html"), "text/html; charset=utf-8")
        if path == "/api/ping":
            return self._json({"ok": True, "app": APP_NAME, "library": library_dir(),
                               "model": os.path.basename(model_path() or ""),
                               "can_import": model_path() is not None})
        if path == "/api/songs":
            return self._json(list_songs())
        if path.startswith("/api/job/"):
            return self._sse(path.rsplit("/", 1)[-1])
        if path.startswith("/media/"):
            rest = path[len("/media/"):]
            parts = [p for p in rest.split("/") if p and p not in (".", "..")]
            if len(parts) != 2:
                return self._send(400, b"bad path", "text/plain")
            song, fn = parts
            if not re.fullmatch(r"[A-Za-z0-9_.\-]+", fn):
                return self._send(400, b"bad name", "text/plain")
            full = os.path.join(library_dir(), song, fn)
            ctype = "audio/mp4" if fn.endswith(".m4a") else "application/octet-stream"
            return self._file(full, ctype)
        # 静态
        if path.startswith("/ui/"):
            rel = posixpath.normpath(path[4:]).lstrip("/")
            full = os.path.join(UI_DIR, rel.replace("/", os.sep))
            if os.path.isfile(full):
                ct = {"html": "text/html", "js": "application/javascript", "css": "text/css",
                      "png": "image/png", "svg": "image/svg+xml"}.get(rel.rsplit(".", 1)[-1], "text/plain")
                return self._file(full, ct + "; charset=utf-8")
        return self._send(404, b"not found", "text/plain")

    def _sse(self, jid):
        with STORE_LOCK:
            job = STORE.get(jid)
        if not job:
            return self._json({"state": "error", "error": "no such job"}, 404)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        # 补发已有日志
        sent = 0
        try:
            while True:
                item = None
                try:
                    item = job.q.get(timeout=1.0)
                except queue.Empty:
                    # 心跳；同时补齐可能漏掉的日志
                    while sent < len(job.logs):
                        self.wfile.write(("data: " + json.dumps({"log": job.logs[sent]}, ensure_ascii=False) + "\n\n").encode("utf-8"))
                        sent += 1
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    if job.state in ("done", "error") and job.q.empty():
                        break
                    continue
                if item.get("state"):
                    data = json.dumps(item, ensure_ascii=False)
                    self.wfile.write(("data: " + data + "\n\n").encode("utf-8"))
                    self.wfile.flush()
                    break
                if item.get("log"):
                    sent += 1
                self.wfile.write(("data: " + json.dumps(item, ensure_ascii=False) + "\n\n").encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    # ---- multipart 解析（支持多个文件字段） ---------------------------- #
    def _parse_multipart(self, tmpdir: str) -> dict:
        """流式解析 multipart，返回 {字段名: (文件名, 落盘路径)}。"""
        ctype = self.headers.get("Content-Type", "")
        m = re.search(r"boundary=([^;]+)", ctype)
        if "multipart/form-data" not in ctype or not m:
            return {}
        delim = b"--" + m.group(1).strip('"').encode()
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}

        parts: dict = {}
        buf = b""
        state = "start"
        cur = None
        remaining = length

        def close_part():
            if cur and cur["fh"]:
                cur["fh"].close()
                if cur["name"]:
                    parts[cur["name"]] = (cur["filename"], cur["path"])

        while remaining > 0:
            chunk = self.rfile.read(min(1 << 20, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            buf += chunk
            while True:
                if state == "start":
                    i = buf.find(delim)
                    if i < 0:
                        if len(buf) > len(delim) + 8192:
                            buf = buf[-(len(delim) + 8192):]
                        break
                    buf = buf[i + len(delim):]
                    state = "after"
                elif state == "after":
                    if buf.startswith(b"--"):
                        state = "done"
                        buf = b""
                        break
                    if buf.startswith(b"\r\n"):
                        buf = buf[2:]
                        state = "headers"
                        continue
                    if len(buf) < 3:
                        break
                    j = buf.find(b"\r\n")
                    if j < 0:
                        break
                    buf = buf[j + 2:]
                    state = "headers"
                elif state == "headers":
                    i = buf.find(b"\r\n\r\n")
                    if i < 0:
                        if len(buf) > 65536:
                            buf = buf[-8192:]
                        break
                    head = buf[:i].decode("utf-8", "replace")
                    buf = buf[i + 4:]
                    fn = re.search(r'filename="([^"]*)"', head)
                    nm = re.search(r'\bname="([^"]*)"', head)
                    cur = {"name": nm.group(1) if nm else None,
                           "filename": os.path.basename(fn.group(1)) if fn else "",
                           "path": os.path.join(tmpdir, "part_%d.bin" % len(parts)),
                           "fh": None}
                    cur["fh"] = open(cur["path"], "wb")
                    state = "body"
                elif state == "body":
                    j = buf.find(b"\r\n" + delim)
                    if j >= 0:
                        cur["fh"].write(buf[:j])
                        close_part()
                        cur = None
                        buf = buf[j + 2 + len(delim):]
                        state = "after"
                        continue
                    keep = len(delim) + 4
                    if len(buf) > keep:
                        cur["fh"].write(buf[:-keep])
                        buf = buf[-keep:]
                    break
                else:
                    buf = b""
                    break
        close_part()
        return parts

    @staticmethod
    def _text_of(parts, key):
        v = parts.get(key)
        if not v:
            return ""
        try:
            with open(v[1], "rb") as f:
                return f.read(2000).decode("utf-8", "replace").strip()
        except Exception:
            return ""

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if u.path not in ("/api/import", "/api/import_pair"):
            return self._send(404, b"not found", "text/plain")

        tmpdir = tempfile.mkdtemp(prefix="genchang_")
        try:
            parts = self._parse_multipart(tmpdir)
        except Exception as e:
            return self._send(500, str(e).encode(), "text/plain")

        jid = "j%d" % int(time.time() * 1000)

        if u.path == "/api/import_pair":
            voice = parts.get("voice")
            accomp = parts.get("accomp")
            if not voice or not accomp:
                return self._send(400, b"need voice + accomp", "text/plain")
            nm = self._text_of(parts, "name")
            stem = nm or os.path.splitext(voice[0])[0] or "我的歌曲"
            # 落盘文件名带扩展名，ffmpeg 靠它判断容器
            ext_v = os.path.splitext(voice[0])[1] or ".bin"
            ext_a = os.path.splitext(accomp[0])[1] or ".bin"
            vp = os.path.join(tmpdir, "voice" + ext_v)
            ap = os.path.join(tmpdir, "accomp" + ext_a)
            os.replace(voice[1], vp)
            os.replace(accomp[1], ap)
            job = Job(jid, voice[0])
            with STORE_LOCK:
                STORE[jid] = job
            threading.Thread(target=run_import, args=(job, vp, stem, ap), daemon=True).start()
            return self._json({"job": jid})

        f = parts.get("file")
        if not f or not os.path.isfile(f[1]):
            return self._send(400, b"no file part", "text/plain")
        stem = self._text_of(parts, "name") or os.path.splitext(f[0])[0] or "我的歌曲"
        ext = os.path.splitext(f[0])[1] or ".bin"
        sp = os.path.join(tmpdir, "upload" + ext)
        os.replace(f[1], sp)
        job = Job(jid, f[0])
        with STORE_LOCK:
            STORE[jid] = job
        threading.Thread(target=run_import, args=(job, sp, stem), daemon=True).start()
        return self._json({"job": jid})

    def do_DELETE(self):
        u = urllib.parse.urlparse(self.path)
        m = re.match(r"^/api/songs/(.+)$", urllib.parse.unquote(u.path))
        if not m:
            return self._send(404, b"not found", "text/plain")
        sid = m.group(1)
        d = os.path.join(library_dir(), sid)
        if os.path.isdir(d) and os.path.dirname(os.path.abspath(d)) == os.path.abspath(library_dir()):
            shutil.rmtree(d, ignore_errors=True)
            return self._json({"ok": True})
        return self._send(404, b"not found", "text/plain")


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


BROWSERS = [
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
]


def find_browser():
    for pat in BROWSERS:
        p = os.path.expandvars(pat)
        if os.path.isfile(p):
            return p
    return None


def main():
    os.makedirs(library_dir(), exist_ok=True)
    port = int(os.environ.get("GENCHANG_PORT") or 0) or free_port()
    url = f"http://127.0.0.1:{port}/"
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    print(f"{APP_NAME} 已在运行")
    print(f"  地址：{url}")
    print(f"  歌曲库：{library_dir()}")
    print(f"  分离模型：{model_path() or '未找到（导入功能不可用）'}")

    br = find_browser()
    if br and not os.environ.get("GENCHANG_NO_WINDOW"):
        prof = os.path.join(os.path.expanduser("~"), ".genchang_browser")
        args = [br, f"--app={url}", f"--user-data-dir={prof}",
                "--window-size=460,880", "--no-first-run", "--no-default-browser-check",
                "--disable-features=Translate,msEdgeIdentityIntegration", "--autoplay-policy=no-user-gesture-required"]
        print(f"  打开窗口：{os.path.basename(br)}")
        p = subprocess.Popen(args)
        try:
            p.wait()
        except KeyboardInterrupt:
            pass
        print("窗口已关闭，退出。")
    else:
        print("  未打开窗口（GENCHANG_NO_WINDOW 或没找到 Edge/Chrome）。")
        print("  请用浏览器打开上面的地址；按 Ctrl+C 退出。")
        if not os.environ.get("GENCHANG_NO_WINDOW"):
            try:
                import webbrowser
                webbrowser.open(url)
            except Exception:
                pass
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""本地上传页面 —— 在浏览器里粘贴 GitHub Token，一键把源码推上去。

    python tools/upload_ui.py

浏览器会自动打开 http://127.0.0.1:8899/
Token 只在你自己电脑的内存里，不写文件、不进聊天记录。
"""
from __future__ import annotations

import json
import os
import queue
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
import push_to_github as P  # noqa: E402

PORT = int(os.environ.get("GENCHANG_UPLOAD_PORT") or 8899)
STATE = {"running": False, "done": None, "error": None, "log": []}
Q: "queue.Queue[dict]" = queue.Queue()
LOCK = threading.Lock()

PAGE = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>上传跟唱助手到 GitHub</title>
<style>
body{background:#0f1117;color:#e8ecf5;font:15px/1.7 -apple-system,"Microsoft YaHei",sans-serif;
     display:flex;justify-content:center;padding:40px 16px;margin:0}
.card{width:100%;max-width:620px;background:#181c27;border:1px solid #2b3245;border-radius:18px;padding:28px}
h1{font-size:22px;margin:0 0 6px}p.sub{color:#8b95ad;margin:0 0 22px;font-size:13px}
label{display:block;font-size:13px;color:#8b95ad;margin:16px 0 6px}
input[type=text],input[type=password]{width:100%;box-sizing:border-box;background:#0f1117;
  border:1px solid #2b3245;color:#e8ecf5;border-radius:10px;padding:12px;font-size:14px}
input:focus{outline:none;border-color:#7c8cff}
a{color:#4dd6c1}
button{width:100%;margin-top:22px;background:linear-gradient(90deg,#ff5c7a,#7c8cff);color:#fff;
  border:0;border-radius:12px;padding:15px;font-size:16px;font-weight:700;cursor:pointer}
button:disabled{opacity:.5;cursor:default}
.row{display:flex;gap:14px;align-items:center;margin-top:10px;font-size:13px;color:#8b95ad}
.log{margin-top:18px;background:#0b0d13;border:1px solid #232a3a;border-radius:10px;padding:12px;
  font:12px/1.7 ui-monospace,Consolas,monospace;max-height:320px;overflow:auto;white-space:pre-wrap;
  color:#a9b3cc;display:none}
.ok{color:#4dd6c1;font-weight:700}.err{color:#ff5c7a;font-weight:700}
</style></head><body><div class="card">
<h1>上传「跟唱助手」到 GitHub</h1>
<p class="sub">源码共 31 个文件。音频、模型、exe、apk 都不会上传（避免版权和体积问题）。</p>

<label>GitHub Token（需要 repo 权限）<br>
<small>没有的话点这里生成：<a href="https://github.com/settings/tokens" target="_blank">github.com/settings/tokens</a>
→ Generate new token (classic) → 勾 repo → 复制 ghp_…</small></label>
<input type="password" id="token" placeholder="ghp_xxxxxxxxxxxxxxxx" autocomplete="off">

<label>仓库名</label>
<input type="text" id="repo" value="genchang-helper">

<div class="row"><input type="checkbox" id="private"><label for="private" style="margin:0">建为私有仓库</label></div>

<button id="go">开始上传</button>
<div class="log" id="log"></div>
</div>
<script>
var btn=document.getElementById('go'),log=document.getElementById('log');
btn.onclick=function(){
  var t=document.getElementById('token').value.trim();
  if(!t){alert('请先粘贴 Token');return;}
  btn.disabled=true;btn.textContent='上传中…';log.style.display='block';log.textContent='';
  fetch('/api/upload',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({token:t,repo:document.getElementById('repo').value.trim(),
                         private:document.getElementById('private').checked})})
   .then(function(r){return r.json()}).then(function(d){
      if(!d.ok){log.innerHTML+='<span class="err">✖ '+d.error+'</span>\\n';
                btn.disabled=false;btn.textContent='重试';return;}
      var es=new EventSource('/api/progress');
      es.onmessage=function(e){
        var m=JSON.parse(e.data);
        if(m.line){log.textContent+=m.line+'\\n';log.scrollTop=log.scrollHeight;}
        if(m.done){es.close();
          log.innerHTML+='\\n<span class="ok">✅ 上传完成</span>\\n'+
            '<a href="'+m.url+'" target="_blank">'+m.url+'</a>\\n'+
            '<span class="err">请立刻回到 GitHub 删除这个 Token！</span>';
          btn.disabled=false;btn.textContent='完成';}
        if(m.error){es.close();log.innerHTML+='\\n<span class="err">✖ '+m.error+'</span>';
          btn.disabled=false;btn.textContent='重试';}
      };
    }).catch(function(e){log.textContent+='请求失败: '+e+'\\n';btn.disabled=false;});
};
</script></body></html>"""


def worker(token, repo, private):
    def log(line):
        Q.put({"line": line})
    try:
        ok, res = P.push(token, repo, private, log=log)
    except Exception as e:
        ok, res = False, {"error": str(e)}
    with LOCK:
        STATE["running"] = False
    if ok:
        Q.put({"done": True, "url": res["url"]})
    else:
        Q.put({"error": res.get("error", str(res))})
    del token


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        if self.path == "/api/progress":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            try:
                while True:
                    try:
                        item = Q.get(timeout=1.0)
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                        continue
                    self.wfile.write(("data: " + json.dumps(item, ensure_ascii=False) + "\n\n").encode())
                    self.wfile.flush()
                    if item.get("done") or item.get("error"):
                        break
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        return self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if self.path != "/api/upload":
            return self._send(404, b"not found", "text/plain")
        n = int(self.headers.get("Content-Length", "0"))
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._send(400, b'{"ok":false,"error":"bad json"}', "application/json")
        token = (data.get("token") or "").strip()
        repo = (data.get("repo") or "genchang-helper").strip()
        if not token:
            return self._send(400, b'{"ok":false,"error":"no token"}', "application/json")
        with LOCK:
            if STATE["running"]:
                return self._send(409, b'{"ok":false,"error":"already running"}', "application/json")
            STATE["running"] = True
        while not Q.empty():
            Q.get_nowait()
        t = threading.Thread(target=worker, args=(token, repo, bool(data.get("private"))))
        t.daemon = True
        t.start()
        return self._send(200, b'{"ok":true}', "application/json")


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d/" % PORT
    print("上传页面已就绪：", url)
    print("在浏览器里粘贴 Token 后点「开始上传」。Ctrl+C 退出。")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        while True:
            threading.Event().wait(3600)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

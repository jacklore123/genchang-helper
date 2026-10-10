#!/usr/bin/env python3
"""「伴奏分离器」—— 极简版：给一个 MP3/MP4/WAV，吐出伴奏和人声。

两种用法：
  * 双击打开 → 点「选择歌曲文件」
  * 直接把歌曲文件拖到 exe 上 → 立刻开始
输出：与源文件同目录的 <歌名>-伴奏.m4a 和 <歌名>-人声.m4a
"""
import os
import queue
import sys
import threading
import traceback

import tkinter as tk
from tkinter import filedialog, messagebox

FROZEN = getattr(sys, "frozen", False)
BASE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))) if FROZEN \
    else os.path.dirname(os.path.abspath(__file__))

if FROZEN:
    ffdir = os.path.join(BASE, "_ffmpeg")
    if os.path.isdir(ffdir):
        for f in os.listdir(ffdir):
            if f.lower().endswith(".exe"):
                os.environ.setdefault("IMAGEIO_FFMPEG_EXE", os.path.join(ffdir, f))
                break
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "engine"))

AUDIO = [("音频 / 视频", "*.mp3 *.wav *.flac *.m4a *.aac *.ogg *.opus *.wma *.mp4 *.mkv *.mov *.avi *.webm"),
         ("所有文件", "*.*")]

C = {"bg": "#141821", "card": "#1e2330", "fg": "#eef1f8", "dim": "#8b95ad",
     "line": "#2c3346", "brand": "#ff5c7a", "ok": "#4dd6c1"}


class App:
    def __init__(self, root, initial=None):
        self.root = root
        self.q = queue.Queue()
        self.busy = False
        self.last_dir = None

        root.title("伴奏分离器")
        root.configure(bg=C["bg"])
        root.geometry("520x360")
        root.minsize(460, 340)
        try:
            root.iconbitmap(os.path.join(BASE, "ui", "app.ico"))
        except Exception:
            pass

        tk.Label(root, text="🎵  伴奏分离器", bg=C["bg"], fg=C["fg"],
                 font=("Microsoft YaHei UI", 17, "bold")).pack(pady=(22, 4))
        tk.Label(root, text="把原唱里的伴奏抽出来（AI 分离，本地运行，不上传）",
                 bg=C["bg"], fg=C["dim"], font=("Microsoft YaHei UI", 9)).pack()

        box = tk.Frame(root, bg=C["card"], highlightbackground=C["line"],
                       highlightthickness=1)
        box.pack(fill="both", expand=True, padx=22, pady=16)

        self.drop = tk.Label(box, text="把 MP3 / MP4 / WAV 拖到这里\n\n或者点下面的按钮选择",
                             bg=C["card"], fg=C["dim"], justify="center",
                             font=("Microsoft YaHei UI", 11), height=5)
        self.drop.pack(fill="both", expand=True, padx=14, pady=(14, 6))

        self.btn = tk.Button(box, text="选择歌曲文件", command=self.choose,
                             bg=C["brand"], fg="#fff", activebackground="#e04a68",
                             activeforeground="#fff", relief="flat", bd=0,
                             font=("Microsoft YaHei UI", 12, "bold"), cursor="hand2")
        self.btn.pack(fill="x", padx=14, pady=(0, 12), ipady=9)

        self.msg = tk.Label(root, text="准备就绪", bg=C["bg"], fg=C["dim"],
                            font=("Microsoft YaHei UI", 9))
        self.msg.pack()
        self.bar = tk.Canvas(root, height=6, bg=C["bg"], highlightthickness=0)
        self.bar.pack(fill="x", padx=22, pady=(6, 4))
        self.fill = self.bar.create_rectangle(0, 0, 0, 6, fill=C["ok"], width=0)
        self.bar.bind("<Configure>", lambda e: self.set_bar(self.pct))

        self.openBtn = tk.Button(root, text="打开输出文件夹", command=self.open_dir,
                                 bg=C["card"], fg=C["fg"], activebackground=C["line"],
                                 activeforeground=C["fg"], relief="flat", bd=0,
                                 font=("Microsoft YaHei UI", 9), cursor="hand2",
                                 state="disabled")
        self.openBtn.pack(pady=(2, 16))
        self.pct = 0.0

        root.after(120, self.pump)
        if initial:
            root.after(200, lambda: self.start(initial))

    # ---------------------------------------------------------------- #
    def set_bar(self, p):
        self.pct = p
        w = self.bar.winfo_width()
        self.bar.coords(self.fill, 0, 0, int(w * p / 100.0), 6)

    def say(self, text, color=None):
        self.msg.configure(text=text, fg=color or C["dim"])

    def choose(self):
        if self.busy:
            return
        p = filedialog.askopenfilename(title="选择歌曲文件", filetypes=AUDIO)
        if p:
            self.start(p)

    def open_dir(self):
        if self.last_dir and os.path.isdir(self.last_dir):
            try:
                os.startfile(self.last_dir)
            except Exception:
                pass

    def start(self, path):
        if self.busy:
            return
        if not os.path.isfile(path):
            messagebox.showerror("伴奏分离器", "找不到文件：\n%s" % path)
            return
        self.busy = True
        self.btn.configure(state="disabled", text="正在分离…")
        self.openBtn.configure(state="disabled")
        self.set_bar(0)
        self.say("准备中…")
        self.drop.configure(text=os.path.basename(path))
        threading.Thread(target=self.work, args=(path,), daemon=True).start()

    def work(self, path):
        try:
            import build_pack
            from mdx_engine import auto_params
            out_dir = os.path.dirname(os.path.abspath(path))

            def prog(m):
                s = str(m)
                self.q.put(("log", s))
                import re
                mm = re.search(r"进度\s+(\d+)/(\d+)", s)
                if mm:
                    a, b = int(mm.group(1)), int(mm.group(2))
                    self.q.put(("pct", 5 + 88.0 * a / max(1, b)))
                elif s.startswith("解码"):
                    self.q.put(("pct", 3.0))
                elif s.startswith("分离模型"):
                    self.q.put(("pct", 6.0))
                elif s.startswith("编码"):
                    self.q.put(("pct", 94.0))

            mp = os.path.join(BASE, "models", "UVR-MDX-NET-Inst_HQ_3.onnx")
            if not os.path.isfile(mp):
                raise RuntimeError("找不到分离模型 models/UVR-MDX-NET-Inst_HQ_3.onnx")

            name = os.path.splitext(os.path.basename(path))[0]
            pack = build_pack.build(path, out_dir, name, mp, progress=prog)

            # build_pack 会生成 original/instrumental/vocals + song.json，
            # 这里整理成用户看得懂的文件名（只留伴奏和人声，原唱就是源文件本身）
            import shutil
            stem_dir = os.path.join(out_dir, name)
            outs = {}
            for key, label in (("instrumental", "伴奏"), ("vocals", "人声")):
                src = os.path.join(stem_dir, key + ".m4a")
                if os.path.isfile(src):
                    dst = os.path.join(out_dir, "%s-%s.m4a" % (name, label))
                    shutil.move(src, dst)
                    outs[label] = dst
            for junk in ("song.json", "original.m4a"):
                try:
                    os.remove(os.path.join(stem_dir, junk))
                except OSError:
                    pass
            shutil.rmtree(stem_dir, ignore_errors=True)
            self.q.put(("pct", 100))
            self.q.put(("done", (out_dir, outs)))
        except Exception as e:
            self.q.put(("err", str(e) + "\n\n" + traceback.format_exc()))

    def pump(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "pct":
                    self.set_bar(val)
                    self.say("正在分离… %d%%" % int(val))
                elif kind == "log":
                    s = str(val)
                    if s.startswith("  时长"):
                        self.say("音频" + s.strip()[2:] if s.strip().startswith("时长") else s)
                    elif "完成，用时" in s:
                        self.say(s.strip())
                elif kind == "done":
                    out_dir, outs = val
                    self.busy = False
                    self.btn.configure(state="normal", text="再处理一首")
                    self.openBtn.configure(state="normal")
                    self.last_dir = out_dir
                    self.set_bar(100)
                    names = "、".join(outs.keys()) or "（无输出）"
                    self.say("✅ 完成：%s" % names, C["ok"])
                    self.drop.configure(
                        text="已生成：%s\n\n都放在：\n%s" % (names, out_dir))
                    messagebox.showinfo("伴奏分离器", "分离完成！\n\n已生成：%s\n\n放在：\n%s"
                                        % (names, out_dir))
                elif kind == "err":
                    self.busy = False
                    self.btn.configure(state="normal", text="选择歌曲文件")
                    self.say("❌ 失败", C["brand"])
                    messagebox.showerror("伴奏分离器", val)
        except queue.Empty:
            pass
        self.root.after(150, self.pump)


def main():
    initial = None
    for a in sys.argv[1:]:
        if os.path.isfile(a):
            initial = a
            break
    root = tk.Tk()
    App(root, initial)
    root.mainloop()


if __name__ == "__main__":
    main()

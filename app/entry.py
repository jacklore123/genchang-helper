#!/usr/bin/env python3
"""「跟唱助手」打包入口。

启动流程（为了"双击就直接用"的体验）：
  1. 立刻弹一个很小的启动画面（不等任何重依赖，先让用户看到反应）
  2. 后台启动本地服务
  3. 打开应用窗口，然后收掉启动画面
全程只访问 127.0.0.1，不需要联网。
"""
import os
import sys
import threading
import time

FROZEN = getattr(sys, "frozen", False)
BASE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))) if FROZEN \
    else os.path.dirname(os.path.abspath(__file__))

# 随包携带的 ffmpeg
if FROZEN:
    ffdir = os.path.join(BASE, "_ffmpeg")
    if os.path.isdir(ffdir):
        for f in os.listdir(ffdir):
            if f.lower().endswith(".exe") or f.lower() == "ffmpeg":
                os.environ.setdefault("IMAGEIO_FFMPEG_EXE", os.path.join(ffdir, f))
                break
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "engine"))


# --------------------------------------------------------------------------- #
def make_splash():
    """在后台线程里起一个 tkinter 启动画面。

    注意：tkinter 的对象只能在创建它的线程里操作，所以整个"创建 + mainloop"
    都放在同一个线程，主线程只通过 flag 通知它关闭。
    返回一个带 close() 的句柄，失败时返回 None。
    """
    state = {"root": None, "done": False, "ready": threading.Event()}

    def run():
        try:
            import math
            import tkinter as tk

            W, H = 300, 168
            root = tk.Tk()
            root.overrideredirect(True)
            root.attributes("-topmost", True)
            try:
                root.attributes("-alpha", 0.97)
            except Exception:
                pass
            sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
            root.geometry("%dx%d+%d+%d" % (W, H, (sw - W) // 2, int(sh * 0.30)))
            root.configure(bg="#161a24")

            c = tk.Canvas(root, width=W, height=H, bg="#161a24", highlightthickness=0)
            c.pack(fill="both", expand=True)
            cx, cy, R, pr = W // 2, 66, 34, 20
            for i in range(5):
                a = -math.pi / 2 + i * 2 * math.pi / 5
                px, py = cx + R * math.cos(a), cy + R * math.sin(a)
                c.create_oval(px - pr, py - pr, px + pr, py + pr, fill="#ff5c7a", outline="")
                c.create_oval(px - pr * 0.7, py - pr * 0.8, px + pr * 0.5, py + pr * 0.4,
                              fill="#ff96aa", outline="")
            cr = 9
            c.create_oval(cx - cr, cy - cr, cx + cr, cy + cr, fill="#ffe27a", outline="")
            c.create_text(W // 2, H - 62, text="跟唱助手", fill="#ffffff",
                          font=("Microsoft YaHei UI", 15, "bold"))
            txt = c.create_text(W // 2, H - 34, text="正在启动…", fill="#8b95ad",
                                font=("Microsoft YaHei UI", 10))
            state["root"] = root
            state["ready"].set()

            dots = ["正在启动", "正在启动.", "正在启动..", "正在启动..."]
            n = [0]

            def tick():
                if state["done"]:
                    try:
                        root.destroy()
                    except Exception:
                        pass
                    return
                try:
                    n[0] = (n[0] + 1) % 4
                    c.itemconfigure(txt, text=dots[n[0]])
                except Exception:
                    pass
                root.after(360, tick)

            root.after(300, tick)
            root.mainloop()
        except Exception:
            state["ready"].set()

    threading.Thread(target=run, daemon=True).start()
    state["ready"].wait(timeout=3.0)
    if state["root"] is None:
        return None
    return state


def close_splash(state):
    if state:
        state["done"] = True


def show_error(msg):
    try:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk()
        r.withdraw()
        messagebox.showerror("跟唱助手 启动失败", msg)
        r.destroy()
    except Exception:
        try:
            with open(os.path.join(os.path.expanduser("~"), "跟唱助手-错误.log"),
                      "w", encoding="utf-8") as f:
                f.write(msg)
        except Exception:
            pass


def main():
    splash = make_splash()
    try:
        import server
    except Exception:
        import traceback
        close_splash(splash)
        time.sleep(0.4)
        show_error("加载程序出错：\n\n" + traceback.format_exc())
        return

    def ready():
        close_splash(splash)

    try:
        server.main(on_ready=ready)
    except Exception:
        import traceback
        close_splash(splash)
        time.sleep(0.4)
        show_error(traceback.format_exc())
    finally:
        close_splash(splash)


if __name__ == "__main__":
    main()

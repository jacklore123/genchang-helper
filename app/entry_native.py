"""原生窗口入口（pywebview / WebView2）。

比 Edge --app 模式更"像一个软件"：没有浏览器外壳、没有地址栏、
不会弹标签页、不碰用户平时的浏览器配置。失败时自动退回 Edge 模式。
"""
import os
import sys
import threading
import time

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


def native_available():
    try:
        import webview  # noqa: F401
        return True
    except Exception:
        return False


def run_native():
    """用 pywebview 起原生窗口。返回 True 表示正常结束。"""
    import webview
    import server

    os.makedirs(server.library_dir(), exist_ok=True)
    server.seed_library()
    port = int(os.environ.get("GENCHANG_PORT") or 0) or server.free_port()
    url = "http://127.0.0.1:%d/" % port
    from http.server import ThreadingHTTPServer
    srv = ThreadingHTTPServer(("127.0.0.1", port), server.Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    server.LAST_PING[0] = time.time()

    win = webview.create_window(
        "跟唱助手", url,
        width=460, height=900, min_size=(360, 560),
        background_color="#12131A", text_select=False, confirm_close=False)

    def on_closed():
        # 窗口关掉就结束进程，别留下后台服务（这个是权威信号，
        # 比心跳猜测可靠得多）
        time.sleep(0.3)
        os._exit(0)

    try:
        win.events.closed += on_closed
    except Exception:
        pass

    # 注意：原生窗口模式**不启用心跳守卫**。
    # 窗口关闭事件已经能准确告诉我们什么时候该退出，
    # 再叠一层"多久没收到 ping 就自杀"只会误杀（页面重载、
    # WebView2 初始化慢、后台标签页降频都可能触发）。
    webview.start()                 # 阻塞到窗口关闭
    return True


def main():
    if native_available() and os.environ.get("GENCHANG_FORCE_BROWSER") != "1":
        try:
            run_native()
            return
        except Exception:
            import traceback
            try:
                with open(os.path.join(os.path.expanduser("~"), "跟唱助手-原生窗口失败.log"),
                          "w", encoding="utf-8") as f:
                    f.write(traceback.format_exc())
            except Exception:
                pass
    # 退回 Edge --app 模式
    import server
    server.main()


if __name__ == "__main__":
    main()

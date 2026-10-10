"""把成品（exe / apk / 歌词纸条 / 伴奏）作为 GitHub Release 发布。

为什么不用仓库文件：
    GitHub 仓库单文件上限 100 MB，而跟唱助手.exe 有 200 MB 左右，
    直接放进仓库会被拒。Release 资产单个可到 2 GB，而且用户点一下就能下载，
    比 clone 仓库再找文件方便得多。

所以的分工：
    仓库   = 源码（.py / .html / .java / 工作流 / 文档）
    Release = 成品（exe / apk / docx / mp3）

用法：
    set GH_TOKEN=...
    python tools/publish_release.py --repo genchang-helper --tag v1.0
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

OWNER = "jacklore123"
API = "api.github.com"
UPLOAD_HOST = "uploads.github.com"

# 资产名一律用 ASCII。
# 中文名在 http.client 的请求行里会被 GitHub 解析坏（实测变成 default.exe / -.mp3），
# 而且中文下载链接在别处也容易出问题。这里用英文名 + 发布说明里的中文对照表。
ASSET_NAMES = {
    "跟唱助手.exe": "genchang-helper-windows.exe",
    "跟唱助手.apk": "genchang-helper-android.apk",
    "伴奏分离器.exe": "accompaniment-separator-windows.exe",
    "紫荆花盛开-伴奏.mp3": "zijinghuashengkai-accompaniment.mp3",
    "合唱歌词小纸条（打印用）.docx": "lyrics-cards-A4.docx",
    "使用说明.txt": "README-zh.txt",
}


def api(method, path, token, data=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request("https://" + API + path, data=body, method=method)
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "genchang-release")
    if body:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"message": raw}


def upload_asset(owner, repo, rel_id, token, path, name):
    """流式上传，避免把 200MB 整个读进内存。"""
    size = os.path.getsize(path)
    q = urllib.parse.quote(name, safe="")
    conn = http.client.HTTPSConnection(UPLOAD_HOST, timeout=1800)
    conn.putrequest("POST", "/repos/%s/%s/releases/%d/assets?name=%s"
                    % (owner, repo, rel_id, q))
    conn.putheader("Authorization", "Bearer " + token)
    conn.putheader("Content-Type", "application/octet-stream")
    conn.putheader("Content-Length", str(size))
    conn.putheader("User-Agent", "genchang-release")
    conn.endheaders()
    sent = 0
    t0 = time.time()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            conn.send(chunk)
            sent += len(chunk)
            if sent % (20 * 1024 * 1024) < 1024 * 1024:
                pct = sent * 100.0 / max(1, size)
                mb = sent / 1e6
                sp = mb / max(0.1, time.time() - t0)
                print("      %5.1f%%  %6.1f MB  %.1f MB/s" % (pct, mb, sp), flush=True)
    resp = conn.getresponse()
    body = resp.read().decode("utf-8", "replace")
    conn.close()
    if resp.status in (200, 201):
        return json.loads(body)
    raise RuntimeError("上传失败 HTTP %s: %s" % (resp.status, body[:300]))


RELEASE_BODY = """## 跟唱助手 · 紫荆花盛开版

一边原唱、一键切伴奏的课堂跟唱工具。**下载对应文件就能用，不需要装任何环境。**

| 下载文件 | 就是 | 给谁用 |
|---|---|---|
| **`genchang-helper-windows.exe`** | 跟唱助手.exe | 电脑（Windows）· 双击就用，已内置《紫荆花盛开》 |
| **`genchang-helper-android.apk`** | 跟唱助手.apk | 学生手机（安卓）· 传过去点一下安装 |
| `accompaniment-separator-windows.exe` | 伴奏分离器.exe | 老师备课 · 把 MP3/MP4 拖上去 → 出伴奏和人声 |
| `zijinghuashengkai-accompaniment.mp3` | 紫荆花盛开-伴奏.mp3 | 舞台/音响 · 320k MP3，拷 U 盘直接放 |
| `lyrics-cards-A4.docx` | 合唱歌词小纸条.docx | 打印 · 一页 A4 六张，剪开发给同学 |
| `README-zh.txt` | 使用说明.txt | 先看这个 |

> 资产名用英文是为了下载链接稳定（中文名会被服务端解析坏），文件内容全是中文，不影响使用。

### 怎么用

打开就是一个干净的歌词界面，跟着进度逐字变色；
**正在唱的那句最大、下一句也放大**，教室后排看得清。

底部一条控制栏：

```
[原唱 | 伴奏]   A·B   ▶   1.0×
   跟唱   只听人声   预备拍   歌词 +0.0s   字号 大
```

- **点「伴奏」立刻切换**，声音无缝、播放进度不跳
- 歌词点任意一句 = 直接跳到那句
- 底部「字号」有 标准 / 大 / 特大 三档，投影建议用**特大**
- 右上角 ☰ 里有：混音滑杆、歌曲库、导入新歌、导入歌词

键盘：`空格` 播放/暂停　`Tab` 切原唱/伴奏　`A` 打 A-B 点　`←/→` 快退快进　`+/-` 歌词字号

### 换歌（泛化能力）

- **只有原唱** → 拖进「伴奏分离器」，本地 AI 分离出伴奏（3 分钟的歌约 40 秒）
- **已有官方伴奏** → 「☰ → 导入新歌 · 已有官方伴奏」，音质零损失，自动对齐时间轴
- **没有歌词** → 导入 `.lrc` 或纯文本歌词，程序会用分离出的人声自动并轨

### 版本说明

本版修掉的问题：

- **切伴奏没声音** —— 之前程序的存活判断绑在浏览器启动器进程上，
  启动器一退出本地服务就被杀，界面还开着但所有新请求都失败；
  现在改成页面心跳保活（并且必须收到过真实心跳才可能回收）
- **点击卡住不动** —— 播放改为三轨并发起播 + 超时兜底，任何一轨异常都不再拖住界面
- **切换不丝滑** —— 20ms 线性交叉淡化，同一母带分离出的两轨高度相关，听感无缝
- **同步纠偏把声音卡死** —— 从每帧渲染循环里移出，改成独立守卫 + 冷却
- **弹黑窗** —— 所有 ffmpeg 调用加 CREATE_NO_WINDOW
- **弹网页** —— 改用 WebView2 原生窗口，没有浏览器外壳

### 版权提醒

分离出来的伴奏仅供教学、排练等**非商业**用途。
仓库和发布包都不含原唱音频，请勿用于商业传播。
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="genchang-helper")
    ap.add_argument("--owner", default=OWNER)
    ap.add_argument("--tag", default="v1.0")
    ap.add_argument("--name", default=None)
    ap.add_argument("--delivery", default=None)
    ap.add_argument("--draft", action="store_true")
    args = ap.parse_args()

    token = os.environ.get("GH_TOKEN")
    if not token:
        sys.exit("请先设置 GH_TOKEN 环境变量")

    delivery = args.delivery or os.environ.get("GENCHANG_DELIVERY") or \
        os.path.join(os.path.dirname(ROOT), "跟唱助手-紫荆花版")
    if not os.path.isdir(delivery):
        sys.exit("交付目录不存在：%s" % delivery)

    assets = []
    for f in sorted(os.listdir(delivery)):
        full = os.path.join(delivery, f)
        if os.path.isfile(full):
            assets.append((full, ASSET_NAMES.get(f, f)))
    if not assets:
        sys.exit("交付目录是空的：%s" % delivery)

    print("发布 %s/%s  标签 %s" % (args.owner, args.repo, args.tag))
    print("资产 %d 个，合计 %.1f MB" % (len(assets),
                                       sum(os.path.getsize(p) for p, _ in assets) / 1e6))
    for p, n in assets:
        print("   %-40s %8.1f MB" % (n, os.path.getsize(p) / 1e6))

    # 已存在同名 tag 就复用
    st, rel = api("GET", "/repos/%s/%s/releases/tags/%s" % (args.owner, args.repo, args.tag),
                  token)
    if st == 200:
        print("\n该标签已存在，复用它（id=%s）" % rel["id"])
    else:
        st, rel = api("POST", "/repos/%s/%s/releases" % (args.owner, args.repo), token, {
            "tag_name": args.tag,
            "target_commitish": "main",
            "name": args.name or ("跟唱助手 · 紫荆花盛开版 %s" % args.tag),
            "body": RELEASE_BODY,
            "draft": bool(args.draft),
            "prerelease": False,
        })
        if st not in (200, 201):
            sys.exit("创建 Release 失败：%s %s" % (st, rel))
        print("\n已创建 Release id=%s" % rel["id"])

    rel_id = rel["id"]
    existing = {a["name"]: a for a in rel.get("assets", [])}

    # 清掉上一次传坏的资产（名字不对的）
    bad = [a for a in rel.get("assets", []) if a["name"] not in {n for _, n in assets}]
    for a in bad:
        st, _ = api("DELETE", "/repos/%s/%s/releases/assets/%d"
                    % (args.owner, args.repo, a["id"]), token)
        print("清理无用资产 %s → HTTP %s" % (a["name"], st))

    for path, name in assets:
        if name in existing:
            print("\n跳过（已存在）：%s" % name)
            continue
        print("\n上传 %s  (%.1f MB)…" % (name, os.path.getsize(path) / 1e6), flush=True)
        try:
            a = upload_asset(args.owner, args.repo, rel_id, token, path, name)
            print("   ✓ %s  →  %s" % (name, a.get("browser_download_url", "")))
        except Exception as e:
            print("   ✗ %s 失败：%s" % (name, e))

    st, rel = api("GET", "/repos/%s/%s/releases/tags/%s" % (args.owner, args.repo, args.tag),
                  token)
    print("\n" + "=" * 60)
    print("发布页：%s" % rel.get("html_url", ""))
    for a in rel.get("assets", []):
        print("   %-42s %7.1f MB  下载 %d 次"
              % (a["name"], a["size"] / 1e6, a.get("download_count", 0)))
    print("=" * 60)


if __name__ == "__main__":
    main()

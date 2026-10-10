#!/usr/bin/env python3
"""把本仓库推送到 GitHub —— 只用 REST API，不需要安装 git。

命令行用法：
    set GH_TOKEN=ghp_xxxx
    python tools/push_to_github.py --repo genchang-helper

图形化用法（推荐，Token 不经过聊天记录）：
    python tools/upload_ui.py

Token 需要 repo 权限：https://github.com/settings/tokens
上传内容遵循 .gitignore：音频、模型、构建产物都不会被推上去。
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

quote = urllib.parse.quote

API = "https://api.github.com"
SKIP_DIRS = {".git", "__pycache__", ".build", "build", "dist", "发布",
             "node_modules", ".vscode", ".idea", "app/models"}
# 这些目录整体不上传（内容另有安排）
SKIP_PREFIX = ("android/assets/", "library/")
SKIP_EXT = {".onnx", ".th", ".m4a", ".mp3", ".wav", ".flac", ".aac", ".ogg",
            ".opus", ".mp4", ".mkv", ".webm", ".apk", ".exe", ".pyc", ".docx",
            ".idsig"}
KEEP = {"songs/README.md", "library/.gitkeep"}


def collect_files(root):
    out = []
    for base, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs
                         if d not in SKIP_DIRS and (not d.startswith(".") or d == ".github"))
        for f in files:
            full = os.path.join(base, f)
            rel = os.path.relpath(full, root).replace("\\", "/")
            if rel in KEEP:
                out.append((full, rel))
                continue
            if rel.startswith(SKIP_PREFIX):
                continue
            if f.startswith(".") and not rel.startswith(".github/") and rel != ".gitignore":
                continue
            if os.path.splitext(f)[1].lower() in SKIP_EXT:
                continue
            if os.path.getsize(full) > 90 * 1024 * 1024:
                continue
            out.append((full, rel))
    return sorted(out, key=lambda x: x[1])


def api(method, path, token, data=None):
    url = API + path
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "genchang-push")
    if body:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"message": raw}
    except Exception as e:
        return 0, {"message": str(e)}


def push(token, repo, private=False, branch="main",
         message="feat: 跟唱助手 —— 一键原唱/伴奏切换", log=print):
    """返回 (ok, 结果字典)。log 用来回报进度。"""
    code, me = api("GET", "/user", token)
    if code != 200:
        return False, {"error": "Token 无效或没有权限：%s" % me.get("message", me)}
    owner = me["login"]
    log("登录账号：%s" % owner)

    code, info = api("GET", "/repos/%s/%s" % (owner, repo), token)
    if code == 404:
        log("仓库不存在，创建 %s/%s …" % (owner, repo))
        code, res = api("POST", "/user/repos", token, {
            "name": repo, "private": bool(private),
            "description": "跟唱助手 —— 一边原唱一边伴奏，一键切换；Windows exe + Android apk",
            "auto_init": False, "has_issues": True, "has_wiki": False,
        })
        if code not in (200, 201):
            return False, {"error": "创建仓库失败：%s" % res.get("message", res)}
        log("仓库已创建")
        time.sleep(2)
    elif code != 200:
        return False, {"error": "查询仓库失败(%d)：%s" % (code, info.get("message", info))}

    files = collect_files(common.ROOT)
    log("准备上传 %d 个文件（已排除音频/模型/程序）" % len(files))

    # 用 Contents API 逐文件提交：对空仓库/首次推送最稳，
    # Git Data API 在刚初始化完的仓库上偶发 404。
    ok_n, skip_n, fail = 0, 0, []
    for i, (full, rel) in enumerate(files, 1):
        with open(full, "rb") as f:
            content = base64.b64encode(f.read()).decode()
        code, cur = api("GET", "/repos/%s/%s/contents/%s" % (owner, repo, quote(rel)), token)
        sha = cur.get("sha") if code == 200 and isinstance(cur, dict) else None
        payload = {"message": "%s: %s" % (message, rel), "content": content}
        if sha:
            payload["sha"] = sha
        code, res = api("PUT", "/repos/%s/%s/contents/%s" % (owner, repo, quote(rel)), token, payload)
        if code in (200, 201):
            ok_n += 1
            log("[%d/%d] %s" % (i, len(files), rel))
        else:
            msg = res.get("message", res) if isinstance(res, dict) else res
            # 内容没变时 GitHub 也会返回 200/201，走到这里才算真失败
            fail.append("%s → %s" % (rel, msg))
            log("[%d/%d] ✗ %s → %s" % (i, len(files), rel, msg))

    if fail:
        return False, {"error": "有 %d 个文件上传失败：%s" % (len(fail), fail[:3])}

    url = "https://github.com/%s/%s" % (owner, repo)
    log("完成：%s" % url)
    return True, {"url": url, "owner": owner, "repo": repo, "files": len(files)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="genchang-helper", help="仓库名")
    ap.add_argument("--private", action="store_true", help="建私有仓库")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--message", default="feat: 跟唱助手 —— 一键原唱/伴奏切换")
    args = ap.parse_args()

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        import getpass
        token = getpass.getpass("请粘贴 GitHub Personal Access Token（不会显示）: ").strip()
    if not token:
        raise SystemExit("没有 token")

    ok, res = push(token, args.repo, args.private, args.branch, args.message)
    if not ok:
        raise SystemExit(res.get("error", str(res)))
    print("\n✅ 完成：%s" % res["url"])


if __name__ == "__main__":
    main()

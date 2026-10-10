#!/usr/bin/env python3
"""把成品集中到一个干净的文件夹 —— 只放用户真正要的东西。

    python tools/pack_delivery.py [目标目录]

默认目标：项目同级的 发布-跟唱助手 目录（可用 GENCHANG_DELIVERY 覆盖）。
最终只有 4 个文件：跟唱助手.exe / 跟唱助手.apk / 伴奏分离器.exe / 使用说明.txt
"""
from __future__ import annotations

import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

APP = "跟唱助手"
SEP = "伴奏分离器"

README = """╔══════════════════════════════════════════════════════════╗
║                  跟唱助手 · 使用说明                       ║
║        一边原唱，一个大按钮，一键切成伴奏                   ║
╚══════════════════════════════════════════════════════════╝

这个文件夹里只有 4 样东西：

  ① 跟唱助手.exe     ← 电脑上双击这个（已内置《紫荆花盛开》）
  ② 跟唱助手.apk     ← 传到学生手机，点一下安装
  ③ 伴奏分离器.exe   ← 想加新歌时用：把 MP3/MP4 拖到它上面
  ④ 合唱歌词小纸条（打印用）.docx  ← 一页 A4 六张，剪开给同学

──────────────────────────────────────────────────────────
① 跟唱助手（电脑 / 手机）

  打开就能用。界面很干净，中间是跟着进度逐字变色的歌词，
  右下角一条控制栏：

      [原唱 | 伴奏]     ← 点一下切换，播放进度不跳
      A·B               ← 反复练某一句（播到开头按一下，到结尾再按一下）
      ▶ / ❚❚            ← 播放 / 暂停
      1.0×              ← 速度，0.5×～1.25×，不跑调

  下面一行灰字：
      跟唱       弱原唱 + 伴奏，跟着唱
      只听人声   只听人声，学旋律
      预备拍     按播放先数 4 / 8 秒
      歌词 +0.0s 整体微调歌词对齐（±0.2 秒一档）

  歌词上点任意一句 = 直接跳到那句。
  右上角 ☰ 里有：混音滑杆、A-B 清除、歌曲库、导入新歌、导入歌词。

  键盘：空格 = 播放/暂停    Tab = 切换原唱/伴奏
        A = 打 A-B 点       ←/→ = 快退快进 5 秒

  手机和电脑操作完全一样。

──────────────────────────────────────────────────────────
② 加新歌（两种方式）

  【方式一】只有原唱 → 让电脑自己分离出伴奏
      点「☰ 歌曲」→「＋ 导入新歌 · 只有原唱」→ 选文件
      3 分钟的歌大约 40 秒处理完（有显卡更快）

  【方式二】已有官方伴奏 → 音质零损失（推荐）
      点「＋ 导入新歌 · 已有官方伴奏」
      先选原唱，再选伴奏，程序自动对齐时间轴

  手机上导入：点「＋ 导入新歌」，先选原唱，再选伴奏
  （手机不做 AI 分离，分离请在电脑上做，或用下面的分离器）

──────────────────────────────────────────────────────────
③ 伴奏分离器（只想抽伴奏时用）

  把 MP3 / MP4 / WAV 直接拖到「伴奏分离器.exe」上，
  或者双击打开再选文件。

  会在歌曲旁边生成：
      <歌名>-伴奏.m4a
      <歌名>-人声.m4a

  不上传、不联网，全部在本地算。

──────────────────────────────────────────────────────────
④ 歌词怎么办

  内置的《紫荆花盛开》已经带好歌词了。

  新导入的歌如果没有歌词，有两种办法：

  A) 导入 .lrc 歌词文件（推荐，最准）
     歌曲列表里点那首歌右边的「＋词」→ 选 .lrc 文件
     程序会自动把它对齐到你这版录音上（自动并轨）

  B) 导入纯文本歌词（一行一句，没有时间轴）
     也能导入，程序会按人声区间把句子吸附到起唱点上。
     精度不如 .lrc，可以用界面上的「↕」微调。

  ⚠ 注意：歌词文件的时间轴通常是给「官方发行版」写的。
    如果你手上是翻唱、不同语言版本、或另一个母带，
    一定要用「＋词」导入让程序重新对齐，否则歌词会整体偏几秒。

──────────────────────────────────────────────────────────
⑤ 常见问题

  Q 杀毒软件报警？
  A 自己打包的绿色软件，没有购买数字签名，加信任即可。

  Q 双击后没反应？
  A 单文件版首次启动要解压，等 3～6 秒（有启动画面）。

  Q 换台电脑还能用吗？
  A 能。整个文件夹拷过去就行；自己导入的歌在 exe 同级的
    library 文件夹里，一起拷走即可。

  Q 切原唱/伴奏会不会跳？
  A 不会。两条音轨是采样级对齐的（实测 0 采样偏差），
    切换只是 45 毫秒的淡入淡出。

──────────────────────────────────────────────────────────
⑥ 版权提醒

  歌曲是有版权的。请在合理使用范围内用于课堂教学：
    · 不要把歌曲音频上传到公开的代码仓库
    · 不要把包含歌曲的安装包公开分发
  分享给别人时只给程序，让对方自己导入音频。
"""


def main():
    dst = os.environ.get("GENCHANG_DELIVERY") or \
        (sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(common.ROOT),
                                                           "跟唱助手-紫荆花版"))
    os.makedirs(dst, exist_ok=True)

    items = [(os.path.join(common.DIST, APP + ".exe"), APP + ".exe"),
             (os.path.join(common.RELEASE, APP + ".apk"), APP + ".apk"),
             (os.path.join(common.DIST, SEP + ".exe"), SEP + ".exe")]
    # 歌词小纸条（打印用）
    docx = os.environ.get("GENCHANG_LYRICS_DOCX") or \
        os.path.join(os.path.dirname(common.ROOT),
                     "紫荆花盛开-合唱歌词小纸条(6张·一页A4)-已同步时间.docx")
    if os.path.isfile(docx):
        items.append((docx, "合唱歌词小纸条（打印用）.docx"))
    else:
        print("  [!] 没找到歌词小纸条：%s" % docx)
    # 兼容目录版
    for src, name in ((os.path.join(common.DIST, APP), None),
                      (os.path.join(common.DIST, SEP), None)):
        if name is None and os.path.isdir(src):
            print("提示：%s 是目录版，跳过（用 --onedir 打包时才会有）" % os.path.basename(src))

    def copy_retry(src, dst, tries=8):
        import time
        last = None
        for i in range(tries):
            try:
                shutil.copy2(src, dst)
                return True
            except PermissionError as e:      # 常被杀软/资源管理器短暂占用
                last = e
                time.sleep(1.2)
        print("  [!] 复制失败 %s：%s" % (os.path.basename(src), last))
        return False

    ok = 0
    for src, name in items:
        if os.path.isfile(src):
            if copy_retry(src, os.path.join(dst, name)):
                print("  %-24s %6.1f MB" % (name, os.path.getsize(src) / 1e6))
                ok += 1
        else:
            print("  [!] 缺 %s（%s）" % (name, src))

    with open(os.path.join(dst, "使用说明.txt"), "w", encoding="utf-8") as f:
        f.write(README)
    print("  使用说明.txt")
    print("\n交付目录: %s   （%d 个程序）" % (dst, ok))
    for f in sorted(os.listdir(dst)):
        p = os.path.join(dst, f)
        if os.path.isfile(p):
            print("   %8.1f MB  %s" % (os.path.getsize(p) / 1e6, f))


if __name__ == "__main__":
    main()

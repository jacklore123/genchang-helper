"""把「最终版源码」单独复制一份到指定文件夹。

复制的内容和上传到 GitHub 的**完全一致**（同一套收集规则），
所以这个文件夹既可以直接打包发给别人，也可以直接 git init 推上去。

用法：
    python tools/make_source_folder.py [目标文件夹]
    （默认 F:\\跟唱助手-源码，可用环境变量 GENCHANG_SOURCE 覆盖）
"""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
from push_to_github import collect_files  # noqa: E402

README = """跟唱助手 · 最终版源码
====================================================================

这个文件夹里的东西，和 GitHub 仓库 https://github.com/jacklore123/genchang-helper
上一模一样，是同一套文件、同一套收集规则生成的。

目录结构
--------------------------------------------------------------------
  app/                  主程序（Python + 网页界面）
    server.py           本地服务：歌曲库、音轨、歌词、导入接口
    entry_native.py     程序入口：原生窗口（WebView2），失败自动退回 Edge
    entry.py            旧入口（Edge --app 模式，保留兼容）
    separate.py         独立的「伴奏分离器」窗口程序
    ui/index.html       全部界面（电脑和手机共用这一份）
    ui/app.ico          图标
    engine/             音频引擎
      mdx_engine.py     UVR-MDX-NET 人声/伴奏分离（ONNX 推理）
      run_sep.py        解码 + 跑分离 + 写文件
      build_pack.py     只有原唱时 → 生成整套跟唱包
      build_pair.py     已有官方伴奏时 → 对齐时间轴生成跟唱包
      align_lyrics.py   歌词自动并轨（全局偏移 + 逐行吸附）
      subproc.py        统一子进程调用（保证不闪 cmd 黑窗）
    seed/               内置歌曲（只放歌词和时间轴，音频不入库）

  android/              安卓端（不依赖 Gradle，aapt2 + javac + d8 直接编）
    src/com/genchang/player/
      MainActivity.java 界面容器
      MiniHttp.java     手机本地的 HTTP 服务（支持 Range）
      Songs.java        读取 assets 里的歌曲
      MediaMeta.java    M4A 元数据解析
    AndroidManifest.xml
    res/drawable/icon.png

  tools/                构建与发布脚本
    build_exe.py        打包 Windows 单文件 exe（PyInstaller）
    build_apk.py        打包安卓 apk（不需要 Android Studio）
    pack_delivery.py    生成给老师用的交付文件夹 + 导出舞台用伴奏 MP3
    make_source_folder.py  就是本脚本，导出这份源码
    push_to_github.py   把源码推到 GitHub
    fetch_model.py      下载分离模型
    make_pack.py        命令行生成跟唱包
    make_lyrics.py      生成歌词
    common.py           路径与公共变量

  ci/                   工作流内容（GitHub 的 workflow 权限受限时的备用）
  .github/workflows/    两个自动化工作流
  docs/                 使用说明
  lyrics/               歌词源文件（LRC）
  songs/                放歌的目录（音频不会提交）

怎么跑起来
--------------------------------------------------------------------
  1) 装依赖
       pip install -r requirements.txt      # 如果没有该文件，见下面
       实际用到：numpy onnxruntime soundfile imageio-ffmpeg pywebview
  2) 下载分离模型（约 60 MB，仓库里不放模型）
       python tools/fetch_model.py
  3) 直接开发运行
       python app/entry_native.py           # 原生窗口
       python app/entry.py                  # 或 Edge 窗口模式
  4) 打包
       python tools/build_exe.py            # → dist/跟唱助手.exe
       python tools/build_exe.py separate   # → dist/伴奏分离器.exe
       python tools/build_apk.py            # → 发布/跟唱助手.apk
  5) 生成交付文件夹
       python tools/pack_delivery.py

换一首歌
--------------------------------------------------------------------
  · 只有原唱：把 MP3/MP4 拖到「伴奏分离器.exe」上，或
       python tools/make_pack.py <原唱文件> -o library
  · 已有官方伴奏（音质零损失）：
       python tools/make_pack.py <原唱> --accomp <伴奏> -o library
  · 歌词：把 .lrc 和歌曲放同一个目录，程序启动时会自动并轨

注意
--------------------------------------------------------------------
  * 音频、模型、打包产物都不在仓库里（见 .gitignore）。
    请勿把有版权的音频提交到公开仓库。
  * 分离出来的伴奏只可用于教学、排练等非商业用途。
"""


def main():
    if len(sys.argv) > 1:
        dst = sys.argv[1]
    else:
        dst = os.environ.get("GENCHANG_SOURCE") or \
            os.path.join(os.path.dirname(common.ROOT), "跟唱助手-源码")

    files = collect_files(common.ROOT)
    os.makedirs(dst, exist_ok=True)

    n = 0
    for full, rel in files:
        target = os.path.join(dst, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(full, target)
        n += 1

    with open(os.path.join(dst, "源码说明.txt"), "w", encoding="utf-8") as f:
        f.write(README)

    # 顺便生成一个 requirements.txt，方便别人复现环境
    req = os.path.join(dst, "requirements.txt")
    if not os.path.exists(req):
        with open(req, "w", encoding="utf-8") as f:
            f.write("# 运行/打包「跟唱助手」需要的库\n"
                    "numpy\nonnxruntime\nsoundfile\nimageio-ffmpeg\n"
                    "pywebview\npythonnet\npyinstaller\n")

    print("导出 %d 个源码文件 → %s" % (n, dst))
    for full, rel in files:
        print("   ", rel)


if __name__ == "__main__":
    main()

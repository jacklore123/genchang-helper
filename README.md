# 跟唱助手 · GenChang

> 一边是**原唱**，一个大按钮，一键切成**伴奏**。
> 同学们先跟着原唱学，学会了，一按就变伴奏。

电脑（Windows exe）和手机（安卓 apk）都能装，界面完全一样。

---

## 它解决什么问题

教一首歌，最麻烦的是：**原唱和伴奏是两个文件，切换的时候要退出、重开、找进度。**
跟唱助手把两个音轨**采样级对齐**后同时播放，切换时**播放进度不丢**，
还可以在中间任意比例混合（比如"人声 20% + 伴奏 100%"的弱原唱跟唱模式）。

- 🎤 **原唱** ⇄ 🎹 **伴奏**：点一下切换，进度不跳
- 👥 **跟唱**：弱原唱（带一点人声当引导）
- 🎧 **人声**：只听人声，学旋律
- 🔁 **A-B 循环**：反复练某一句
- ⏱ **预备拍**：起唱前给 4/8 秒准备
- 🐢 **变速 0.5×–1.25×**：不跑调
- 📝 **歌词**（可放 `lyrics`，见下）

---

## 快速开始

### 电脑（班级电脑）

1. 下载 `跟唱助手.exe` 所在的整个文件夹
2. 双击 `跟唱助手.exe`
3. 把歌曲文件拖进「导入新歌」→ 等 1–3 分钟 → 自动生成伴奏

导入流程：选中一首歌 → 本地 AI（UVR-MDX-NET）把原唱分离成 `原唱 / 伴奏 / 人声` 三轨 → 存进 `library/<歌名>/`。
也可以用**官方伴奏**（音质最好）：把 `原唱` 和 `伴奏` 两个文件都给它，程序自动对齐，不跑分离。

### 手机（学生手机）

1. 把 `跟唱助手.apk` 传给学生，点安装（需要在系统设置里允许"安装未知来源应用"）
2. 打开即用，内置歌曲可以直接播放
3. 手机上也能导入：导入新歌 → 选「原唱」文件 → 选「伴奏」文件 → 起名

> 手机上不做 AI 分离（算力不够），所以手机导入需要**已经有一对原唱+伴奏**。
> 想让学生自己在手机上把任意一首歌变成伴奏，请先在电脑上处理好，或者用下面的工作流。

---

## 换歌工作流（GitHub Actions）

不用装任何环境，把歌交给 GitHub 跑：

### 方式一：手动触发

`Actions` → `生成跟唱包` → `Run workflow`，填：

| 输入 | 说明 |
|---|---|
| `song_url` | 歌曲直链（音频或视频都行），留空则处理 `songs/` 目录里已有的文件 |
| `song_name` | 歌曲名 |
| `mode` | `separate`（只有原唱，AI 分伴奏）/ `pair`（原唱+伴奏，自动对齐） |
| `accompaniment_url` | `pair` 模式下的伴奏直链 |

跑完在 `Artifacts` 里下载 `genchang-pack`，解压后就是标准的跟唱包目录，丢进电脑版的 `library/` 就能播。

### 方式二：直接 push

```
songs/我的歌/
    voice.mp3        # 原唱（必需）
    accomp.mp3       # 官方伴奏（可选；有它就不做 AI 分离了）
```

push 之后工作流自动跑，产物同样在 Artifacts 里。

> ⚠️ **不要把有版权的歌曲提交到公开仓库。** 见下面「版权」。

---

## 从源码构建

```bash
# 0) 环境：Python 3.10+
pip install numpy onnxruntime soundfile imageio-ffmpeg pyinstaller pillow

# 1) 拉模型（66MB，不进仓库）
python tools/fetch_model.py

# 2) 做跟唱包
python tools/make_pack.py 歌曲.mp3 --name "歌名"
python tools/make_pack.py 原唱.mp4 --accompaniment 官方伴奏.mp4 --name "歌名"
python tools/make_pack.py --scan          # 批量处理 songs/

# 3) 打包电脑版
python tools/build_exe.py                 # → dist/跟唱助手/
python tools/build_exe.py onefile         # → dist/跟唱助手.exe

# 4) 打包安卓版（需要 JDK 17 + Android SDK build-tools;34.0.0 platforms;android-34）
python tools/build_apk.py                 # → 发布/跟唱助手.apk
```

---

## 工作原理

```
歌曲文件 ──ffmpeg──▶ 44.1kHz 立体声 PCM
                          │
                          ▼
              STFT (n_fft 由模型哈希查表得到)
                          │
                          ▼
        UVR-MDX-NET Inst HQ 3  (onnxruntime，DirectML/CPU)
                          │
                          ▼
                   iSTFT + 重叠相加
                          │
              ┌───────────┴───────────┐
              ▼                       ▼
        instrumental.m4a         vocals.m4a (原唱 − 伴奏)
```

- **模型参数不是猜的**：`mdx_engine.py` 用 UVR 官方规则（文件末尾 10,240,000 字节的 MD5）
  去查 `MODEL_REGISTRY`，拿到准确的 `n_fft / dim_f / dim_t / compensate`。
  参数错了频谱会糊，这一步很关键。
- **三轨严格采样对齐**：同一个解码器、同样参数、`original = instrumental + vocals`，
  实测对齐延迟 **0 个采样**，所以切换时不会有位置漂移。
- **前端切换**：两个 `<audio>` 元素同时播放，各挂一个 `GainNode`，
  点按钮就是 45ms 的增益交叉淡化 —— 无缝隙、无爆音、进度连续。
- **打包体积**：exe 289MB（含 ffmpeg 88MB + 模型 64MB）；
  apk 13.5MB（歌曲另算）。

---

## 目录结构

```
跟唱助手/
├── app/
│   ├── entry.py              # 打包入口（定位随包 ffmpeg）
│   ├── server.py             # 本地服务：界面/歌曲库/导入 API（支持 Range）
│   ├── ui/index.html         # 全部界面（电脑手机共用，零依赖单文件）
│   └── engine/
│       ├── mdx_engine.py     # 纯 numpy + onnxruntime 的 MDX-Net 实现
│       ├── run_sep.py        # 解码 / 写 wav
│       ├── build_pack.py     # 一首歌 → AI 分离 → 跟唱包
│       └── build_pair.py     # 原唱+伴奏 → 自动对齐 → 跟唱包
├── android/                  # 安卓工程（不用 Gradle）
│   ├── AndroidManifest.xml
│   └── src/com/genchang/player/
│       ├── MainActivity.java # WebView + 文件选择器导入
│       ├── MiniHttp.java     # 内嵌本地 HTTP 服务（与电脑端同一套 API）
│       ├── Songs.java        # 歌曲库（内置 assets + 用户导入）
│       └── MediaMeta.java
├── tools/                    # 构建与处理脚本
├── library/                  # 跟唱包（不进仓库）
├── songs/                    # 待处理的原始歌曲（不进仓库）
└── .github/workflows/
```

安卓端和电脑端**共用同一个 `app/ui/index.html`**，靠内嵌的本地 HTTP 服务提供同样的
`/api/songs`、`/media/<id>/<文件>` 接口。改一次界面，两端同时生效。

---

## 版权与合规（请务必读）

- 本仓库**只放代码**。歌曲音频、模型权重、ffmpeg 二进制都通过 `.gitignore` 排除，
  不随代码分发。
- 《紫荆花盛开》等歌曲的著作权属于原作者与唱片公司。**请使用你已合法获得的音频**，
  不要从盗版站点抓取，也不要把歌曲提交到公开仓库（会被 DMCA 下架）。
- 本工具生成的是**供教学练习使用的伴奏音轨**，请在合理使用范围内用于课堂。
- 如需公开分享成品，请只分享**代码和空歌曲库**，让使用者自己导入音频。

第三方组件许可证：
- 分离模型 UVR-MDX-NET 系列，来自 [TRvlvr/model_repo](https://github.com/TRvlvr/model_repo)
- [onnxruntime](https://github.com/microsoft/onnxruntime) MIT
- ffmpeg —— 随包使用请注意 LGPL/GPL 条款，本仓库不提交 ffmpeg 二进制

---

## 常见问题

**切换原唱/伴奏时声音会跳吗？**
不会。三轨由同一份 PCM 生成、编码参数一致，实测 0 采样偏差；切换是增益交叉淡化。

**导入一首歌要多久？**
3 分钟的歌约 40 秒（有独显/核显加速时 5× 实时），纯 CPU 约 1× 实时。

**没有官方伴奏怎么办？**
直接丢原唱进去，AI 会分离出伴奏。质量取决于歌曲本身，混响重的歌会稍差。

**手机上能分离吗？**
不能。手机端是播放器 + 导入已做好的原唱/伴奏。分离请在电脑或用工作流做。

---

MIT License · 代码随便用，歌曲请自己合法获取。

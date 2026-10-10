# ci/ —— 放这里是因为 Token 权限

这两个文件本来应该在 `.github/workflows/` 下（仓库里也有一份），
但 GitHub 规定：**用 API 创建/修改 workflow 文件需要 Token 具备 `workflow` 权限**，
只有 `repo` 权限时会被拒（而且 GitHub 把它伪装成 404，看不出是权限问题）。

## 想让它生效，两种办法任选

### 办法一：给 Token 加 `workflow` 权限（30 秒）

1. 打开 https://github.com/settings/tokens
2. 点开你那个 Token → 勾上 **`workflow`** → Update token
3. 运行：
   ```bash
   set GH_TOKEN=你的token
   python tools/push_to_github.py --repo genchang-helper
   ```

### 办法二：在网页上手动放（不用改 Token）

1. 打开仓库 → **Add file** → **Create new file**
2. 文件名填 `.github/workflows/make-accompaniment.yml`
   （输入 `/` 会自动建目录，直接把这整行路径粘进去即可）
3. 把本目录 `make-accompaniment.yml` 的内容整个粘进编辑框 → Commit
4. 对 `build-apps.yml` 重复一次

放好之后 `Actions` 标签页就会出现两个工作流。

---

## 两个工作流各干什么

### `make-accompaniment.yml` —— 换歌就出新伴奏

触发方式：

- **手动**：Actions → 生成跟唱包 → Run workflow，填歌曲直链
- **push**：把歌曲放进 `songs/<歌名>/`（`voice.mp3` 必需，`accomp.mp3` 可选）

跑完在 **Artifacts** 里下载 `genchang-pack`，解压后就是标准的跟唱包目录，
丢进电脑版的 `library/` 就能播。

- 目录里有 `accomp*` / `inst*` / `伴奏*` → 走**官方伴奏模式**，不跑 AI 直接对齐，音质零损失
- 只有原唱 → 走 **AI 分离模式**，本地跑 UVR-MDX-NET 抽掉人声

> ⚠️ `songs/` 和 `library/` 已写进 `.gitignore`，放进去的音频不会被提交。
> 公开仓库里千万别放有版权的歌。

### `build-apps.yml` —— 自动打包 exe / apk

在 GitHub 上给你把 Windows 版和安卓版都打出来，不用本地装 Python、
JDK、Android SDK。手动触发，或者打 `v*` 标签时自动跑。

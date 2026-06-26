# photo-guard

照片防盗用三层防护框架的可执行实现，对应 [`AGENTS.md`](./AGENTS.md) 中规定的方案与技术要求。

> 三层叠加：明水印（防搬运）+ PhotoGuard 对抗扰动（防 AI 二次生成）+ 隐水印（兜底确权）。
> 目标是抬高盗用成本与提供确权能力，不是物理上 100% 阻止。

---

## 这是什么？(给非技术读者)

简单讲，你拍了一张照片，发到社交平台之前，先用本工具「过」一遍，输出一张肉眼看上去几乎一样的图。这张图相比原图多了三件事：

1. **看得见的水印**：半透明文字直接压在照片主体（比如人脸）上，搬运的人想抠掉就得把脸重画一遍；
2. **看不见的水印**：藏在图像频域里的一段唯一署名（比如 `owner:你的名字#日期`），平台压缩、轻度裁剪后还能用 `verify` 命令解出来，证明图是你的；
3. **AI 看不懂的「噪声」**：肉眼几乎察觉不到的微小扰动，但会让任何 AI 改图、换脸、去水印工具拿到这张图时输出崩坏画面。

### 它能做什么 / 不能做什么

| 能做 | 不能做 |
|------|--------|
| 让随手搬运你照片的人留下痕迹（明水印） | 物理上阻止任何人保存你的图 |
| 万一被盗，事后从可疑图里提取唯一署名做证据（隐水印） | 100% 抗住所有平台多次重压缩 + 大幅裁切 |
| 让对方用 AI 一键去水印 / 换脸时大概率失败（PhotoGuard 扰动） | 抗住未来还没出现的新一代 AI 模型 |

一句话：**这是「锁」不是「保险柜」**——抬高成本、留下证据，不保证绝对。

---

## 硬件与系统要求

工具分两档，按你打算用不用「真 PhotoGuard 对抗扰动」走不同路线。

### 档位 A：核心模式（推荐先跑通这一档）

只跑 隐水印 + 明水印 + 占位扰动（轻量噪声），不需要任何 AI 模型。

| 项 | 最低 | 推荐 |
|----|------|------|
| 操作系统 | Linux / macOS / Windows（任意 64 位） | Linux 或 macOS |
| CPU | 任何 x86_64 / Apple Silicon | 4 核以上 |
| 内存 (RAM) | 2 GB | 4 GB |
| 硬盘空间 | 1 GB（含 Python + 依赖 + .venv） | 2 GB |
| GPU | **不需要** | — |
| 网络 | 一次性下载依赖时联网即可 | — |
| Python | 由 `uv` 自动安装 3.11，**无需自己装** | — |

处理一张 1080p 图片：常规笔记本上 1–3 秒。

### 档位 B：完整模式（开启真 PhotoGuard SD-encoder 攻击）

启用 `--perturber sd` 时会加载 Stable Diffusion VAE 模型（~335 MB），CPU 也能跑但会明显变慢。

| 项 | 最低 | 推荐 |
|----|------|------|
| 操作系统 | Linux / macOS / Windows 64 位 | Linux + NVIDIA 驱动 |
| 内存 (RAM) | 8 GB | 16 GB |
| 硬盘空间 | 6 GB（torch + diffusers + 模型缓存约 4–5 GB） | 10 GB |
| GPU（可选） | 无（落到 CPU，慢但能跑） | NVIDIA 显卡，显存 ≥ 4 GB（fp16） |
| 网络 | 首次运行需下载 ~335 MB 模型 + ~3 GB torch 系包 | — |
| Docker 替代路径 | 镜像 ~5.5 GB（已烘入模型 + torch + uv），运行时 0 网络请求 | `docker run --gpus all ...` 一键 |

处理一张 1080p 图片：
- **CPU**：10 步 PGD 大约 30 秒～1 分钟（图越大越慢）
- **GPU**：10 步 PGD 通常 1–3 秒

> **说明**：模型默认从 HuggingFace（`stabilityai/sd-vae-ft-mse`）下载到 `~/.cache/huggingface/`。如果机器不能直连国外，可以提前自己设好镜像或代理。

### Windows 系统支持

代码本身没有 POSIX-only 假设，**两条路径都能跑**：

| 路径 | 状态 | 说明 |
|------|------|------|
| 原生 uv | ✅ CI 已覆盖 `windows-latest`（fast tier） | torch 2.12.1 在 Windows 走单一 wheel，自带 CUDA runtime；不会触发 Linux 的"装一堆独立 nvidia 包"问题 |
| Docker Desktop + WSL2 | ✅ 与 Linux 镜像完全一致 | PowerShell 里挂载工作目录用 `${PWD}` 而不是 `$PWD` |

PowerShell 用法示例（核心模式）：

```powershell
# 装 uv（一次性）
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 跑（注意 ${PWD} 而不是 $PWD）
git clone https://github.com/INORI-LIN/photo_cyber.git
cd photo_cyber
uv sync --frozen
uv run python -m photo_guard protect C:\path\to\me.jpg `
    -o C:\path\to\me_protected.jpg `
    --visible-text "© me"

# 或者走 Docker Desktop（要求开 WSL2 backend）
docker run --rm -v "${PWD}:/work" photo-guard:dev `
    protect /work/me.jpg -o /work/me_protected.jpg
```

GPU 支持需要 Windows + NVIDIA 驱动，`torch.cuda.is_available()` 会自动选 CUDA 路径，无需额外配置。

> 说一句实话：Windows fast-tier CI 已绿（`uv sync` + `pytest -m 'not slow'`），但**完整模式（`--perturber sd` 真 PhotoGuard 攻击）** 在 Windows 上没专门测过。理论上能跑——torch wheel 在；如果你是第一个在 Windows 上跑完整模式的用户，欢迎提 issue。

---

## 最快路径：Docker 一键跑（推荐零配置首次使用）

如果你只想拿来用、不想折腾 Python / uv / 模型下载，用 Docker 最快：

```bash
# 用本仓库自己 build 一份镜像（首次约 5–10 分钟，之后走缓存）
git clone https://github.com/INORI-LIN/photo_cyber.git
cd photo_cyber
docker build -t photo-guard:dev .

# 保护一张图（CPU）：把图所在目录挂到 /work
docker run --rm -v "$PWD:/work" photo-guard:dev \
    protect /work/me.jpg -o /work/me_protected.jpg \
    --payload "owner:me#2026" \
    --visible-text "© me"

# 启用真 PhotoGuard SD-encoder 攻击（CPU 慢，GPU 加 --gpus all 即可）
docker run --rm --gpus all -v "$PWD:/work" photo-guard:dev \
    protect /work/me.jpg -o /work/me_protected.jpg --perturber sd

# 验证（确权）
docker run --rm -v "$PWD:/work" photo-guard:dev \
    verify /work/me_protected.jpg --payload-bytes 14
```

镜像里**已烘入** SD VAE（`stabilityai/sd-vae-ft-mse`，~335 MB）+ Python 3.11 + uv + torch/diffusers，运行时 `HF_HUB_OFFLINE=1` 强制离线，再没有任何外网请求。GPU 主机加 `--gpus all` 自动走 CUDA；不加就老实跑 CPU。

镜像大小约 **5.5–6 GB**（torch + nvidia 运行时 wheel 占大头）。

> 想把镜像 push 到 ghcr.io / Docker Hub？看 `.github/workflows/docker.yml`，本仓库默认只 build + 烟雾测试，不 push，发包逻辑由你自己决定。

---

## 按需开关三层防护（`--layers`）

默认三层全开（`invisible,perturb,visible`）。如果你只想要一部分，用 `--layers` 列出想保留的层（逗号分隔，任意非空子集都可以）：

```bash
# 只要隐水印 + 明水印（跳过 AI 干扰）
docker run --rm -v "$PWD:/work" photo-guard:dev \
    protect /work/in.jpg -o /work/out.jpg \
    --layers invisible,visible

# 只要隐水印（用于纯确权场景）
... --layers invisible

# 只要 PhotoGuard 干扰（不嵌水印、不打明水印）
... --layers perturb --perturber sd

# 隐水印 + AI 干扰，不打明水印（适合不希望主体上有可见文字的场景）
... --layers invisible,perturb --perturber sd
```

> **执行顺序锁死**：无论你选哪几层，运行顺序永远是 `① invisible → ② perturb → ③ visible`（AGENTS.md §二，不可调）。`--layers` 只决定哪些层**出现**，不决定**先后**。
>
> **降级警告**：关掉任意一层都会削弱整体防护——隐水印挡确权、AI 干扰挡换脸/重绘、明水印挡随手搬运，三者本来是互补的。

---

## 5 分钟上手（从零到出第一张保护图）

> 不想用 Docker 才看这一节。Docker 路径见上。

### 第 1 步：装 `uv`

`uv` 是一个新的 Python 包管理器，替代 `pip`。本项目**强制用 uv**，不用自己折腾 Python 版本。

Linux / macOS：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Windows（PowerShell）：

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

装完后关掉终端再开一个，输入 `uv --version` 能看到版本号即成功。

### 第 2 步：拿到代码 + 装依赖

```bash
git clone https://github.com/INORI-LIN/photo_cyber.git
cd photo_cyber

# uv 会自动下载 Python 3.11 并建立 .venv，不会污染系统 Python
uv python install 3.11
uv python pin 3.11
uv sync --frozen          # 装核心依赖（档位 A 够用）
```

完成后项目目录下会多出一个 `.venv/`，里面是隔离好的 Python 环境，你不需要手动激活它。

### 第 3 步：保护一张照片

把要保护的图放到任意位置（比如 `~/Pictures/me.jpg`），然后：

```bash
uv run python -m photo_guard protect ~/Pictures/me.jpg \
  -o ~/Pictures/me_protected.jpg \
  --payload "owner:你的名字#2026-06-25" \
  --visible-text "© 你的名字"
```

跑完会输出类似：

```
protected: /home/you/Pictures/me_protected.jpg  size=1080x810  perturber=noop  payload_bytes=27
```

打开 `me_protected.jpg`，会看到照片主体（一般是脸）上有半透明文字水印。

> **重要**：`--payload` 是嵌入到隐水印里的内容，**它的字节数你必须自己记住**（上面例子是 27 字节，UTF-8 中文一字 3 字节）。验证时要传同样的字节数才能解出。

### 第 4 步：验证一张可疑图（确权）

某天你看到平台上有人盗了你的图，把那张图存下来，跑：

```bash
uv run python -m photo_guard verify suspect.jpg --payload-bytes 27
```

如果还能解出来，会打印出原 payload，说明确实是你的图。如果对方做了大幅二次重绘 / 平台多次重压缩，可能解不出，会提示 `no payload recovered`。

### 第 5 步（可选）：开启真 PhotoGuard 扰动

如果你担心对方用 AI 换脸 / 去水印，加一档防御：

```bash
# 一次性多装 ~3 GB 的 torch + diffusers
uv sync --extra photoguard

# 第一次跑会下载 ~335 MB 的 SD VAE 模型
uv run python -m photo_guard protect ~/Pictures/me.jpg \
  -o ~/Pictures/me_protected.jpg \
  --payload "owner:你的名字#sd" \
  --perturber sd
```

CPU 上慢一点（30 秒～1 分钟），GPU 上几秒。

---

## 常见问题 FAQ

**Q: 可以不用 `uv`，直接 `pip install` 吗？**
A: 不可以。项目硬性规定（见 [`AGENTS.md`](./AGENTS.md) §6），CI 会扫描代码里有没有 `pip install` 字样直接判失败。`uv` 用法和 `pip` 几乎一样，但能锁定 Python 版本和依赖。

**Q: `--payload-bytes` 是什么？为什么我必须记住？**
A: 隐水印解码时算法需要事先知道 payload 长度（位数）才能正确切片。它不是密码，写错只会解不出来不会损坏图。建议 payload 用纯 ASCII（每字符 1 字节）+ 一个固定模板，比如 `owner:xxx#YYYY-MM-DD`，方便记忆。

**Q: 为什么我的输出图分辨率被改成 1080×xxx 了？**
A: 这是设计行为。社交平台普遍会再压一遍图，工具先把长边压到 1080 让最终画面就是「压缩后的形态」，可以减少平台二次压缩对水印的破坏。想保留原分辨率加 `--long-edge 0`（不推荐，会降低水印鲁棒性）。

**Q: 输出文件为什么是 JPEG，不能存 PNG 吗？**
A: 同上，JPEG 是社交平台最终格式，工具直接以平台规格输出，让水印对压缩免疫。强行存 PNG 不在当前 CLI 支持范围内（可改源码）。

**Q: `--perturber sd` 跑得太慢怎么办？**
A: 三个办法：① 减少迭代步数 `--perturber-steps 5`；② 调小 `--long-edge 720` 缩小图；③ 找台带 NVIDIA 显卡的机器跑。CPU 上 1080p × 10 步是基线 30–60 秒。

**Q: 明水印挡住主体太碍眼？**
A: 用 `--visible-mode tile` 切换为全图低透明度网格模式，或 `--visible-mode center` 只压在画面正中。透明度调低用 `--visible-alpha 0.05`。

**Q: 工具支持视频吗？**
A: 不支持，本版本只处理静态图（JPG / PNG / WebP 等 Pillow 能读的）。

---

## 方案概览

| 防护层 | 作用 | 主要针对 |
|--------|------|----------|
| ① 隐形水印（DWT-DCT-SVD） | 肉眼不可见、可提取，用于确权 | 两类威胁均覆盖 |
| ② PhotoGuard 对抗扰动 | 误导扩散模型，使去水印 / 改图 / 换脸重绘崩坏 | AI 二次生成 |
| ③ 明水印（subject / tile / center） | 给人看，与主体纹理交织，擦除即毁图 | 直接盗图搬运 |

执行顺序经过 AGENTS.md 第二节与第五节双约束推导后定为：

```
load → fit_long_edge(1080) → ① 隐水印 embed → ② 扰动 → ③ 明水印 → 保存 JPEG q=85
```

`fit_long_edge` 提到 embed 之前的原因：DWT-DCT 频域水印对几何重采样敏感，先按平台规格 resize 才能让水印嵌入到「成品分辨率」上。这与 AGENTS.md 第五节 checklist 第 1 步「发布前原图长边压到约 1080px」一致。详细推理记录在 `src/photo_guard/pipeline.py` 顶部 docstring。

---

## 项目结构

```
photo_cyber/
├── AGENTS.md                  # 方案与技术要求（不可改）
├── CLAUDE.md                  # 给未来 Claude Code 实例的开发指引
├── README.md                  # 本文件
├── pyproject.toml             # uv 管理的依赖与入口
├── uv.lock                    # 锁定文件，跨机可复现
├── .python-version            # uv 锁定 Python 3.11
├── Dockerfile                 # 单镜像 CPU+GPU；模型 build 时烘入
├── .dockerignore              # 排除 .venv/ models/ tests/ 等
├── .github/workflows/
│   ├── ci.yml                 # ubuntu+windows matrix；fast pytest
│   └── docker.yml             # build + 离线烟雾测试，不 push registry
├── tests/                     # 38 用例 fast tier（约 20s）
└── src/photo_guard/
    ├── __init__.py / __main__.py
    ├── cli.py                 # argparse: protect / verify / download-models
    ├── pipeline.py            # 顺序编排（① → ② → ③）+ --layers 子集
    ├── config.py              # 集中默认参数
    ├── watermark_invisible.py # ① 隐水印（imwatermark, dwtDctSvd）
    ├── perturb.py             # ② Perturber 接口 + Noop / Noise / SDEncoder
    ├── photoguard.py          # ② SD-VAE encoder PGD 攻击（懒加载，离线）
    ├── download.py            # 一次性 SD VAE 下载（唯一允许联网的模块）
    ├── watermark_visible.py   # ③ 明水印（subject / tile / center 三模式）
    ├── subject.py             # ③ 主体检测（haar → Sobel 显著性 → 中心）
    └── compress.py            # 长边 resize 至平台规格
```

---

## 全部 CLI 参数

`protect`：

| 参数 | 默认 | 说明 |
|------|------|------|
| `--payload` | `photo-guard` | 要嵌入的唯一 ID / 署名 |
| `--layers` | `invisible,perturb,visible` | 逗号分隔的子集；任意非空组合都行（如 `invisible,visible` 跳过 AI 干扰）。**执行顺序固定**为 invisible → perturb → visible（AGENTS.md §二），本参数只控开关 |
| `--perturber` | `noop` | `noop` / `noise`（占位）/ `sd`（真 PhotoGuard SD-encoder PGD，需要 `--extra photoguard`） |
| `--visible-mode` | `subject` | `subject` 主体绑定 / `tile` 全图平铺 / `center` 画面中心 |
| `--visible-text` | `© photo-guard` | 明水印文字 |
| `--visible-alpha` | `0.10` | 透明度，5%–15% 区间见 AGENTS.md 三③ |
| `--long-edge` | `1080` | 长边像素 |
| `--quality` | `85` | JPEG 质量 |
| `--perturber-eps` | `8/255` | SD 攻击 L∞ 像素预算（仅 `--perturber sd` 生效） |
| `--perturber-steps` | `10` | SD 攻击 PGD 迭代次数 |
| `--perturber-step-size` | `2/255` | SD 攻击单步符号梯度幅度 |
| `--perturber-model` | `stabilityai/sd-vae-ft-mse` | HuggingFace VAE 模型 ID |

`verify`：

| 参数 | 必填 | 说明 |
|------|------|------|
| `suspect` | 是 | 可疑图路径 |
| `--payload-bytes` | 是 | 原 payload 字节长度（不一致解不出） |

`download-models`（一次性，仅 `--perturber sd` 离线场景需要）：

| 参数 | 默认 | 说明 |
|------|------|------|
| `--repo` | `stabilityai/sd-vae-ft-mse` | HuggingFace repo id |
| `--dest` | `<repo>/models/sd-vae-ft-mse` | 本地落盘目录；`config.PHOTOGUARD_MODEL_ID` 默认就指这里 |

> Docker 镜像在 build 期已自动调用 `download-models`，运行容器时不需要再跑这个。仅当你走原生 uv 路径并且想要 `--perturber sd` 时才需要手动跑一次。

退出码：`0` 成功；`1` 解码后判定无 payload；`2` 运行错误（缺少 extra、文件读不到、`--layers` 含未知名字等）。

---

## 三层实现要点

### ① 隐形水印 — `watermark_invisible.py`

- 库：`invisible-watermark`（`imwatermark.WatermarkEncoder/Decoder`）。
- 算法：**`dwtDctSvd`**（DWT-DCT 系频域方案的 SVD 增强变体）。
- 选型理由：纯 `dwtDct` 在 JPEG q=85 直接全损；SVD 变体在 q=75 仍能 100% 还原，更符合 AGENTS.md 三①「抗压缩、抗缩放、强度调高」的要求。
- 对外接口仅 `embed(bgr, payload)` / `extract(bgr, payload_bytes)` 两个函数，参数控制收敛在 `config.py`。

### ② PhotoGuard 对抗扰动 — `perturb.py` + `photoguard.py`

- 抽象基类 `Perturber.apply(bgr) -> bgr`，注册表 `_REGISTRY` 按名取实例。
- 三个实现：
  - `NoopPerturber`：默认，原样返回，对应 AGENTS.md 三② 原话「预留接入位」。
  - `GaussianNoisePerturber(epsilon=2/255)`：ε-bounded 噪声，肉眼无感的占位实现。
  - `SDEncoderPerturber`：**真 PhotoGuard 实现**——PGD 攻击 Stable Diffusion VAE encoder（`stabilityai/sd-vae-ft-mse`，仅 ~335MB），让 latent 漂移到零向量；任何 img2img / inpainting / 换脸都会以这个被污染的 latent 为起点而崩坏。
- **懒加载**：`SDEncoderPerturber` 的 `apply()` 第一次被调用才会 import torch / diffusers / accelerate 并下载模型；普通用户只 `uv sync` 不会拖几 GB 重依赖。
- **可选 extra**：依赖隔离在 `[project.optional-dependencies].photoguard`，文档第六节合规——所有依赖仍由 `pyproject.toml` + `uv.lock` 锁定，启用方式是 `uv sync --extra photoguard`，不出现 `pip`。
- **CPU/GPU 自适应**：检测 `torch.cuda.is_available()`，CUDA 上 fp16，CPU 上 fp32（慢但可用，256×256 / 2 步 PGD 在常规 CPU 约 35s）。
- **几何对齐**：自动把图像裁到 8 的倍数尺寸（VAE 卷积步长要求），对应 AGENTS.md 五节 1080 长边后会变成 1080×808 之类，肉眼几乎无差。

### ③ 明水印 — `watermark_visible.py`

- 后端：纯 `Pillow` + `subject.py`（用 cv2 自带 haar cascade，无新依赖）。
- 三种模式：
  - `subject`（默认）：`subject.detect_subject` 三级检测——haar 人脸 → Sobel 显著性矩形 → 几何中心兜底——再把半透明水印压在主体框上。这是 AGENTS.md 三③「绑定主体」原话最贴近的实现：擦水印=重绘主体=毁图。
  - `tile`：低透明度文字网格，按 `gap` 间距 + 30° 旋转铺满全图，与主体纹理交织；
  - `center`：半透明文字压在画面几何中心。
- 合成：`Image.alpha_composite`，语义接近 AGENTS.md 三③ 提到的 overlay。

### 主体检测 — `subject.py`

- 完全用 `opencv-python-headless` 已自带的资源，零新依赖。
- 三级 fallback 永远返回一个合理的 `(x, y, w, h)` 框：
  1. **haar frontal-face**（`haarcascade_frontalface_default.xml`，cv2.data 自带 XML）；
  2. **Sobel 显著性**：用积分图 + 滑窗在 O(W·H) 时间内找梯度能量最高的 30% × 30% 矩形；
  3. **几何中心**：上面两步都退化时，落到画面中心 60% 区域。

### 预压缩 — `compress.py`

- 单函数 `fit_long_edge`，LANCZOS 重采样到目标长边。
- 调用位置在 embed 之前（见上文「执行顺序」）。

---

## 开发者指南

### 测试

```bash
uv sync --group dev                  # 装 pytest
uv run pytest -m 'not slow'          # 快速档（约 20s，38 用例）
# 跑完整档（含真 SD 攻击，需要先 uv sync --extra photoguard）
uv run pytest
```

CI 跑两个 workflow：

- `.github/workflows/ci.yml`：matrix 覆盖 `ubuntu-latest` + `windows-latest`，跑 §6.4 grep（仅 Linux，POSIX 工具）+ `uv sync --frozen --group dev` + `pytest -m 'not slow'`。Windows 上 §6.4 由 `tests/test_compliance.py`（纯 Python）兜底。
- `.github/workflows/docker.yml`：build 单镜像（含模型烘入）+ smoke（`protect` + `verify` + `--network none` 离线 SD 攻击），不 push。runner 用 `jlumbroso/free-disk-space@main` 释放 ~30GB（默认 14GB 装不下 torch + nvidia + SD VAE）。

### 合规检查（提交前）

```bash
grep -RIn --exclude-dir=.venv --exclude-dir=.git \
     --exclude=uv.lock --exclude=AGENTS.md --exclude=README.md \
     "pip install" .
# 必须无任何输出
```

### 加新的扰动算法

按 `perturb.py` 现有套路：
1. 写一个继承 `Perturber` 的类，实现 `apply(bgr) -> bgr`；
2. 注册到 `_REGISTRY`；
3. 在 `cli.py` 加对应 CLI flag；
4. 默认参数收敛到 `config.py`。

如果新算法依赖重型框架（如 torch），按 `SDEncoderPerturber` 的懒加载模式：`__init__` 只存配置，import 只在 `apply()` 内部触发，依赖挂到 `[project.optional-dependencies]` 下面。

---

## 已完成 / 进度

- [x] 用 `uv init --package` 初始化 photo-guard 包；`uv python pin 3.11`；锁定 `pyproject.toml` + `uv.lock`
- [x] 三层模块全部实现（隐水印 / 扰动 / 明水印）+ 预压缩 + 集中 `config.py`
- [x] `pipeline.py` 编排正确顺序（修正过一次：resize 提到 embed 前以解决 DWT 对几何重采样敏感的问题）
- [x] `cli.py` 提供 `protect` 与 `verify` 子命令；`__main__.py` / `[project.scripts]` 双入口
- [x] 端到端验证：synthetic 1600×1200 JPG → protect → 1080×810 输出 → verify 正确还原 26 字节 payload
- [x] AGENTS.md 6.4 节合规检查：`requirements.txt` 不存在；除 AGENTS.md 自身外仓库内 `pip install` 命中数 0
- [x] `uv sync --frozen` 复现验证通过
- [x] 把 `opencv-python` 换成 `opencv-python-headless`（避免无头机器缺 `libGL.so.1`）
- [x] **明水印「绑定主体」真实版**：`subject.py` 三级 fallback（haar → Sobel 显著性 → 几何中心），`watermark_visible.apply_subject` 接入；CLI 默认 `--visible-mode=subject`。
- [x] **真 PhotoGuard `SDEncoderPerturber` 接入**：`photoguard.py` 用 PGD 攻击 SD VAE encoder；`[project.optional-dependencies].photoguard` 隔离重依赖；CLI 暴露 `--perturber sd` + `--perturber-eps/-steps/-step-size/-model`；端到端 protect→verify 在 SD 扰动 + JPEG q=85 之后隐水印仍能完整还原。
- [x] **单元测试 + GitHub Actions CI**：`tests/` 7 文件 26 用例覆盖合规（AGENTS.md 6.4 grep）、注册表与 lazy-import 契约、隐水印往返（含 q=85 + 明水印后还原回归）、pipeline 顺序回归、subject 三级 fallback、可见水印三模式 smoke、CLI 退出码（0/1/2）。`.github/workflows/ci.yml` 跑 grep → `uv sync --frozen --group dev` → `pytest -m 'not slow'`。本地：`uv sync --group dev && uv run pytest -m 'not slow'`，全绿约 11s。slow 标记的 SD 攻击测试需 `uv sync --extra photoguard` 后手动跑。
- [x] **离线模型加载**：`config.PHOTOGUARD_MODEL_ID` 切到 `<repo>/models/sd-vae-ft-mse`，`photoguard.py` 用 `local_files_only=True` + `HF_HUB_OFFLINE=1` 锁死运行时不联网；新增 `download.py` + `photo-guard download-models` 子命令做唯一一次性联网下载。
- [x] **Docker 开箱即用镜像**：`Dockerfile` 单镜像同时支持 CPU/GPU（torch wheel 自带 CUDA runtime），build 期 `RUN download-models` 把 SD VAE 烘入 `/app/models/`，运行时 `HF_HUB_OFFLINE=1` 强制离线。`.github/workflows/docker.yml` build + 烟雾测试（含 `--network none` 验证模型真已烘入），不 push registry。镜像 ~5.5 GB。
- [x] **三层防护可任意子集开关**：`pipeline.ProtectOptions.layers` (frozenset) + CLI `--layers invisible,perturb,visible` 接收任意非空子集；执行顺序按 AGENTS.md §二 锁死，`--layers` 只控开关不控顺序。空集合 / 未知层名 → exit 2。
- [x] **Windows 系统支持**：`watermark_visible._load_font` 加上 macOS / Windows TTF 路径回退（之前只查 Debian/Ubuntu 路径，Windows 上落到 Pillow 默认位图字体导致 `--visible-text` 渲染成 ~10px）；`tests/test_compliance.py` 改为纯 Python `Path.rglob` 实现替代 `subprocess[grep]`，跨平台；CI matrix 加 `windows-latest`。Windows fast tier 38/38 通过。
- [x] **测试规模升到 38 用例**：新增 `tests/test_pipeline_layers.py` 覆盖 7 个非空子集 + 空 + 未知层名共 10 用例；`tests/test_cli_exits.py` 新增 2 用例覆盖 `--layers` CLI 路径。本地 fast tier 约 20s 全绿。

## 待办 / 已知边界

- [ ] **更强的主体检测**：`haar` 漏检侧脸 / 戴口罩 / 小脸，后续可换 `mediapipe` 或 ONNX 化的 RetinaFace；多人脸场景目前只取最大框，可改为多框分别贴。
- [ ] **平台二次压缩鲁棒性**：当前 `dwtDctSvd` 在 q≥75 单次压缩可还原；社交平台多重压缩 + 裁切场景需要更高强度或重复嵌入策略，是 AGENTS.md 第四节自己点出的固有边界。

---

## 参考

- [`AGENTS.md`](./AGENTS.md) — 方案、技术细节、环境管理规范（uv 强制）。
- [invisible-watermark](https://github.com/ShieldMnt/invisible-watermark) — 隐水印实现来源。
- [PhotoGuard (MIT)](https://gradientscience.org/photoguard/) — 对抗扰动方案，已通过 `photoguard.py` 中的 SD-VAE encoder PGD 攻击落地。

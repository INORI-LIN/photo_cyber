# photo-guard

一个离线优先的照片防盗工具，通过三层组合保护降低直接搬运和 AI 二次编辑风险：

1. **隐形水印**：DWT-DCT-SVD 频域嵌入，用于事后确权；
2. **PhotoGuard 对抗扰动**：攻击 Stable Diffusion VAE encoder，增加 AI 去水印、换脸和重绘成本；
3. **明水印**：绑定人脸或主体区域，或以低透明度网格覆盖全图。

> 本工具用于抬高盗用成本并提供确权线索，不承诺阻止保存、截图、全图重绘或未来模型攻击。

## 功能概览

- PySide6 桌面界面，支持拖拽、多选和批量处理；
- 三层保护可独立选择，但执行顺序固定；
- 主体、平铺、居中三种明水印模式；
- 新版隐水印支持版本头和 CRC 完整性校验；
- 批量验证及 CSV 结果导出；
- CPU、NVIDIA CUDA、Apple Metal/MPS 设备选择；
- CLI、Docker 和 Windows/macOS 离线安装包构建；
- 模型只从本地目录加载，保护和验证过程不联网。

## 支持平台与设备

| 平台 | CPU | GPU 加速 | 发布形式 |
|---|---:|---|---|
| Windows x64 | ✅ | NVIDIA CUDA | 安装程序 `.exe` |
| macOS Apple Silicon | ✅ | Apple Metal/MPS | `.dmg` / `.app` |
| Linux | ✅ | NVIDIA CUDA | 源码 / Docker |
| Intel Mac | — | — | 不提供安装包 |

Windows AMD/Intel 显卡和其他适配器会显示在设备列表中，但当前 PhotoGuard 不使用这些设备，会回退 CPU。选择 `Auto` 时按 **CUDA → MPS → CPU** 决定后端；明确选择不可用设备会报错，不会静默切换。

## 桌面版快速开始

### 使用发布安装包

在 GitHub Actions 的 `release-desktop` 工作流中下载对应产物：

- `PhotoGuard-Windows-x64-Setup.exe`
- `PhotoGuard-macOS-arm64.dmg`

完整安装包包含 Qt、PyTorch、diffusers 和 SD VAE，安装后可离线使用。当前构建未进行 Windows 代码签名或 Apple notarization，首次启动可能出现未知开发者提示。

### 从源码启动

项目强制使用 `uv`，不要手动激活虚拟环境：

```bash
uv python install 3.11
uv python pin 3.11
uv sync --frozen --extra desktop
uv run photo-guard-gui
```

若要在 GUI 中启用 PhotoGuard：

```bash
uv sync --frozen --extra desktop --extra photoguard
uv run photo-guard download-models
uv run photo-guard-gui
```

`download-models` 是唯一需要连接 Hugging Face 的模型准备步骤。模型默认保存到项目的 `models/sd-vae-ft-mse/`，之后运行阶段强制使用本地文件。

## GUI 使用说明

### 照片保护

1. 拖入图片或点击“添加图片”；
2. 选择保护操作：隐形水印、PhotoGuard、明水印；
3. 设置 payload、明水印文字、模式、透明度和输出规格；
4. 启用 PhotoGuard 时选择 `Auto`、CPU、CUDA 或 MPS；
5. 选择输出目录，点击“开始保护”。

GUI 默认启用 **隐形水印 + 明水印**。PhotoGuard 默认关闭，避免用户无意启动高耗时任务。批处理按顺序执行并复用已加载的模型，可显示进度、记录单图失败并支持取消。

GUI 生成的隐水印默认带 CRC envelope。payload 本身不会保存到用户设置中，请自行妥善记录。

### 水印验证

- 新版图片：输入原始 payload，工具自动计算存储长度并验证 CRC；
- 旧版图片：填写嵌入时的 payload UTF-8 字节数；
- 批量结果可导出为 CSV。

## CLI 使用

### 核心模式

```bash
uv sync --frozen

uv run photo-guard protect input.jpg \
  -o output.jpg \
  --payload "owner:alice#2026" \
  --visible-text "© Alice"
```

CLI 默认层为 `invisible,visible`，输出 JPEG 长边默认 1080px、质量 85。`--long-edge 0` 表示保持原尺寸。

### 使用新版 CRC payload

```bash
uv run photo-guard protect input.jpg \
  -o output.jpg \
  --payload "owner:alice#2026" \
  --payload-envelope

# 推荐：不告知长度，直接盲检 CRC 信封
uv run photo-guard verify output.jpg

# 也可以核对指定的 payload
uv run photo-guard verify output.jpg \
  --expected-payload "owner:alice#2026"
```

不传任何 flag 时，`verify` 会在候选长度上搜索 `PG1:` 信封，并**只用 CRC32 判定**，因此不需要记住 payload 长度，也不会把随机噪声当成 payload；`--max-payload-bytes` 可调整搜索上界。找到则打印 payload 并退出 0，未找到退出 1。

### 验证旧版图片（仅线索）

```bash
uv run photo-guard verify suspect.jpg --payload-bytes 16
```

`--payload-bytes` 必须等于嵌入内容的 UTF-8 字节数，不一定等于字符数。

旧版 payload 没有校验和，因此这条路径**只给线索、不给结论**：stdout 形如 `线索（未验证）: <内容>`，stderr 打印 `blocks/bit` 与 `mean_margin` 两个辅助指标，**退出码为 3**（`0` 只保留给取回证据的路径，见上方退出码表）。实测（见 `docs/fix-plan.md` §6 P3）：真实产物的 `mean_margin` 落在 0.2567–0.3247，而可打印垃圾可达 0.2005–0.5000，两者完全重叠——**没有任何阈值能区分真伪**，故该路径的结论不可作为确权证据。需要能举证的结论时，请用 `--payload-envelope` 重新保护。

### 启用 PhotoGuard

```bash
uv sync --frozen --extra photoguard
uv run photo-guard download-models

uv run photo-guard protect input.jpg \
  -o output.jpg \
  --layers invisible,perturb,visible \
  --perturber sd \
  --device auto \
  --payload "owner:alice#sd"
```

模型来源与信任边界：`download-models` 从 `stabilityai/sd-vae-ft-mse` 拉取，并钉在不可变的
revision `31f26fdeee1355a5c34592e401dd41e45d25a493`（只取 `*.json` 与 `*.safetensors`）。
加载侧强制 `use_safetensors=True`：目录里没有 safetensors 权重就报错退出，**不会回退到 `.bin`
的 pickle 反序列化**。`--perturber-model` 接受任意本地目录，请只指向自己下载的目录——该目录
内容会被反序列化，等同于信任其来源。

可通过以下命令查看设备：

```bash
uv run photo-guard devices
```

### 常用参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--layers` | `invisible,visible` | 非空子集；不改变顺序；选择 `noise` / `sd` 时自动加入 `perturb` |
| `--payload` | `photo-guard` | 隐水印内容 |
| `--payload-envelope` | 关闭 | 启用版本头和 CRC 校验 |
| `--perturber` | `noop` | `noise` / `sd` 会自动启用 perturb 层；显式启用该层时不能使用 noop |
| `--device` | `auto` | `auto` / `cpu` / `cuda` / `mps` |
| `--device-index` | `None` | 多 CUDA 显卡时指定索引 |
| `--visible-mode` | `subject` | `subject` / `tile` / `center` |
| `--visible-text` | `© photo-guard` | 明水印文字 |
| `--visible-alpha` | `0.10` | 明水印透明度，范围 0–1 |
| `--long-edge` | `1080` | 输出长边；0 保持原尺寸 |
| `--quality` | `85` | JPEG 质量，范围 1–100 |
| `--perturber-eps` | `8/255` | PhotoGuard L∞ 扰动预算 |
| `--perturber-step-size` | `2/255` | PGD 单步大小 |
| `--perturber-steps` | `10` | PGD 迭代次数 |
| `--perturber-model` | 本地模型目录 | 不接受运行时远程加载 |
| `--max-payload-bytes` | `128` | 盲检信封搜索上界 |

`--layers` 仍决定基础层集合；为了避免“选择了扰动器但实际未执行”的误用，`--perturber noise` 和 `--perturber sd` 会自动将 `perturb` 加入最终层集合。

退出码：`0` 成功（含 `verify` 取回证据：信封命中或盲检发现），`1` 未恢复出 payload（三条 verify 路径同此口径：盲检未找到信封、`--expected-payload` 整图找不到信封、`--payload-bytes` 未取回），`2` 参数或运行错误（含请求长度超出图像容量、`--expected-payload` 与图内信封不符、信封 CRC 校验不确定），`3` 只取回旧版线索（`--payload-bytes` 路径，无校验和，**不等于验真通过**）。`verify` 不带 flag 时由「缺参退 2」变为「盲检 0/1」。

`protect` 会拒绝把输出写到输入文件自身（含硬链接别名），报 `refusing to overwrite the input` 并退出 2 —— 原图留底是 AGENTS.md 第五节的硬要求。写盘采用同目录临时文件 + `os.replace`，因此中断、磁盘写满或 Ctrl-C 都不会在成品路径上留下半截文件；已有文件的权限位会沿用，新文件遵循进程 umask。若输出路径是符号链接，`os.replace` 替换的是链接本身、链接指向的文件内容不受影响；但当那个目标文件是只读的时，写盘会临时解除其写保护（`chmod` 加写位）以完成替换，且成功路径不回贴原权限位，目标文件的写位会保留。批量处理时，同名 stem 的输入会自动得到 `_2`、`_3` 后缀，不会互相覆盖（去重对大小写不敏感；Linux 上同样保守生效）。

## 固定处理顺序

```text
读取图片
  → 按 long-edge 缩放
  → ① 嵌入隐形水印
  → ② 添加对抗扰动
  → ③ 添加明水印
  → JPEG 保存
```

`--layers` 可以关闭某一层，但不能调整执行顺序。缩放放在隐水印之前，是因为 DWT-DCT-SVD 对后续几何重采样较敏感。

PhotoGuard 会先将图像边缘补齐到 8 的倍数，处理后裁回原尺寸，因此不会再造成 0–7 像素的尺寸损失，也能处理小尺寸图片。

## Docker

Docker 镜像包含 PhotoGuard 依赖和本地模型，运行时设置离线模式：

```bash
docker build -t photo-guard:dev .

docker run --rm -v "$PWD:/work" photo-guard:dev \
  protect /work/input.jpg -o /work/output.jpg \
  --payload-envelope \
  --payload "owner:alice"

docker run --rm --gpus all -v "$PWD:/work" photo-guard:dev \
  protect /work/input.jpg -o /work/output-sd.jpg \
  --layers invisible,perturb,visible \
  --perturber sd
```

### 冒烟（与 `.github/workflows/docker.yml` 一致）

先在 `fixtures/` 下准备一张 `in.jpg`；镜像名为 `photo-guard:ci`：

```bash
docker build -t photo-guard:ci .

# ① noise 扰动：保护后立刻验证
docker run --rm -v "$PWD/fixtures:/work" photo-guard:ci \
  protect /work/in.jpg -o /work/out.jpg \
  --layers invisible,perturb,visible \
  --payload "ci-test" \
  --perturber noise

docker run --rm -v "$PWD/fixtures:/work" photo-guard:ci \
  verify /work/out.jpg --payload-bytes 7
# 期望 stdout 整行为 线索（未验证）: ci-test、退出码 3 —— 未启用 --payload-envelope，这条路径只给线索

# ② 离线 SD 冒烟：--network none 下仍能跑 PGD，证明镜像内确实烘焙了 SD VAE
docker run --rm --network none -v "$PWD/fixtures:/work" photo-guard:ci \
  protect /work/in.jpg -o /work/out_sd.jpg \
  --layers invisible,perturb,visible \
  --payload "ci-test" \
  --perturber sd \
  --perturber-steps 2 \
  --long-edge 384
```

## 项目结构

```text
src/photo_guard/
├── cli.py                   # protect / verify / devices / download-models
├── config.py                # 对外可调默认值的唯一来源
├── gui.py                   # PySide6 桌面界面与后台批处理
├── gui_logic.py             # GUI 的 Qt-free 逻辑（设置持久化、勾选→层集合）
├── pipeline.py              # 固定顺序编排和参数校验
├── outputs.py               # 原子写盘与批量命名（绝不写输入文件）
├── device.py                # CPU / CUDA / MPS 检测与选择
├── _dwt_dct_svd.py         # 上游 dwtDctSvd 的仓内逐字转录（MIT，见文件头）
├── watermark_invisible.py   # DWT-DCT-SVD + CRC 信封盲检 + 旧版线索路径
├── watermark_visible.py     # subject / tile / center
├── subject.py               # Haar → Sobel 显著性 → 中心降级
├── perturb.py               # 扰动注册表和重依赖懒加载
├── photoguard.py            # SD VAE encoder PGD
├── compress.py              # 输出尺寸处理
├── resources.py             # 源码和打包资源定位（PHOTO_GUARD_RESOURCE_DIR 可覆盖资源根）
└── download.py              # 唯一联网的模型下载入口

packaging/
├── build_desktop.py         # Nuitka 分平台构建（版本只从 pyproject.toml 读）
├── windows-installer.iss    # Windows Inno Setup（版本由 /DMyAppVersion 注入）
├── create_dmg.sh            # macOS DMG
├── smoke_wheel.sh           # sdist/wheel 构建与隔离安装冒烟
└── generate_notices.py      # 生成/校验 THIRD_PARTY_NOTICES.md 的平台段

LICENSE                      # MIT（Copyright (c) 2026 INORI-LIN）
THIRD_PARTY_NOTICES.md       # 第三方声明（按平台段生成，含 SD VAE 权重）
licenses/                    # GPL-3.0 / LGPL-3.0 正文（PySide6/Qt 走 LGPL）
```

## 开发与测试

```bash
# 仅 core 依赖
uv sync --frozen

# 核心开发环境
uv sync --frozen --group dev

# GUI 开发环境
uv sync --frozen --group dev --extra desktop

# 完整 PhotoGuard 环境
uv sync --frozen --group dev --extra desktop --extra photoguard

# 发布构建（桌面 + PhotoGuard + Nuitka 打包工具）
uv sync --frozen --extra desktop --extra photoguard --group package

# 快速测试
uv run pytest -m 'not slow' -q

# GUI 测试（需要 desktop extra；core 环境该档整体 skip）
uv run pytest -m gui -q

# CLI 帮助，以及等价的模块形式调用
uv run photo-guard --help
uv run python -m photo_guard protect input.jpg -o output.jpg --payload "owner:alice#2026"
```

常用运维命令：

```bash
uv run photo-guard download-models   # 一次性下载 SD VAE 到 models/，之后运行阶段强制本地加载
uv run photo-guard devices           # 列出 CPU / CUDA / MPS 与不可用的适配器
uv run photo-guard-gui               # 启动 PySide6 桌面界面
```

新增依赖统一走 uv：主依赖用 `uv add <包名>`，PhotoGuard extra 用 `uv add --optional photoguard <包名>`。

快速档覆盖原有三层顺序、所有层组合、隐水印 JPEG 回环、参数校验、CRC envelope、设备发现；用例数见 `uv run pytest --collect-only -q`。

`slow` marker 已在 `pyproject.toml` 注册，但当前仓库没有标记 `slow` 的用例。真实 SD 慢档需要 `uv sync --frozen --extra photoguard` 并用 `uv run photo-guard download-models` 准备本地模型；快速档全绿不等于 SD 路径有效。

提交前跑一遍合规检查（`AGENTS.md` §6.4：检索被禁字面量，命中即判失败；正则形式可命中多空格写法，`.github/` 不再排除）：

```bash
grep -RInE --exclude-dir=.venv --exclude-dir=.git \
     --exclude=uv.lock --exclude=AGENTS.md --exclude=README.md \
     --exclude=test_compliance.py \
     "pip[[:space:]]+install" .   # 应无输出
```

项目依赖必须写入 `pyproject.toml` 并由 `uv.lock` 锁定；禁止新增 `requirements.txt`，所有 Python 命令统一通过 `uv run` 执行。

## 桌面发布

`.github/workflows/release-desktop.yml` 在以下条件触发：

- GitHub Actions 手动运行；
- 推送 `v*` 版本标签。

Windows 和 macOS 必须在各自 runner 上构建，不能交叉生成。工作流先跑一个 `verify` 作业（锁文件 round-trip、fast 档全绿、tag 与 `pyproject.toml` 版本一致），两个构建作业 `needs: verify`：

1. 使用 `uv.lock` 同步完整依赖；
2. 校验 `THIRD_PARTY_NOTICES.md` 与本机安装环境一致（`packaging/generate_notices.py --check`）；
3. 下载并嵌入 SD VAE；
4. 使用 Nuitka 生成 standalone 应用（`LICENSE`、第三方声明与 `licenses/` 一并打包）；
5. 执行无 GUI 烟雾测试（同时校验许可材料确实在包内）；
6. 生成安装包/DMG 和 SHA-256 文件；
7. 上传 GitHub Actions artifact；tag 推送时同时附到 GitHub Release。

**版本号只住在 `pyproject.toml`**：Nuitka 的 file/product/macos-app 版本、Inno Setup 的 `AppVersion`（经 `/DMyAppVersion=` 注入）与发布闸门都从它读。改版本后请跑 `uv lock && git diff --exit-code -- uv.lock`，tag 必须是 `v<版本>`。

本地构建命令仅应在目标平台执行：

```bash
uv sync --frozen --extra desktop --extra photoguard --group package
uv run photo-guard download-models
uv run python packaging/build_desktop.py
```

分发包本身的冒烟（sdist/wheel 构建 + 隔离安装 + 版本比对，POSIX）在仓库根执行 `packaging/smoke_wheel.sh`。

## 许可与第三方声明

本项目以 MIT 许可发布（`LICENSE`，Copyright (c) 2026 INORI-LIN）。随包分发的第三方内容：

- `THIRD_PARTY_NOTICES.md`：按平台段列出依赖及各自许可证，含随包分发的 `stabilityai/sd-vae-ft-mse` 权重（MIT）；
- `licenses/GPL-3.0.txt`、`licenses/LGPL-3.0.txt`：PySide6/Qt 以 LGPL-3.0 分发，正文随包提供；
- Docker 镜像、macOS bundle 与 Windows 安装器都包含 `LICENSE`、`THIRD_PARTY_NOTICES.md` 与 `licenses/`。

刷新本平台段：`uv run python packaging/generate_notices.py`（须在装了完整依赖的环境里跑）；发布前用 `--check` 校验——它只比当前平台段，缺失或多出都判失败。许可正文与声明属手写件，生成器只读不写。

## 已知边界

- 隐水印可能在大幅裁剪、多轮强压缩或全图重绘后丢失；
- **信封回环不是长度无关的**：实测（2026-09-23，两张测试图 × payload 1–66 字节）修复前本机成品的验真通过率仅 31/66 与 17/66，且失败长度取决于图像与 payload 内容；载体改到亮度通道 + step 72 并修掉库的细节带互换后，本机成品与再叠一轮平台压缩均已 66/66（见 `docs/fix-plan.md` P10/P11）；
- **平台二次压缩是验真的主要敌人**：上传后平台会按 4:2:0 重新采样色度（本机保存同样如此）。实测把成品缩小一半再放大后，**四个参数组合全部无法验真** —— 请把 `verify` 的通过理解为「这个本地文件可读」，不要理解为「上传后仍可验真」；
- Haar 人脸检测对侧脸、遮挡和多人场景能力有限；
- PhotoGuard 效果依赖目标模型族，净化、未来模型或非扩散编辑流程可能绕过；
- 当前没有 Windows AMD/Intel GPU 加速、Intel Mac 包、代码签名或 Apple notarization；
- 项目尚未建立针对主流社交平台的自动化上传/下载压缩基准。

## 参考

- `AGENTS.md`：三层方案与 uv 规范，另含 §八–§十一 仓库实现约定；
- `src/photo_guard/_dwt_dct_svd.py`：频域水印算式（源自 MIT 许可的 invisible-watermark 0.2.0，逐字转录，含完整许可证正文）；
- MIT PhotoGuard：对抗图像编辑思路。

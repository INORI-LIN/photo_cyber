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

旧版 payload 没有校验和，因此这条路径**只给线索、不给结论**：stdout 形如 `线索（未验证）: <内容>`，stderr 打印 `blocks/bit` 与 `mean_margin` 两个辅助指标。实测（见 `docs/fix-plan.md` §6 P3）：真实产物的 `mean_margin` 落在 0.2567–0.3247，而可打印垃圾可达 0.2005–0.5000，两者完全重叠——**没有任何阈值能区分真伪**，故该路径的结论不可作为确权证据。需要能举证的结论时，请用 `--payload-envelope` 重新保护。

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
| `--visible-alpha` | `0.10` | 明水印透明度，范围 0–1 |
| `--long-edge` | `1080` | 输出长边；0 保持原尺寸 |
| `--quality` | `85` | JPEG 质量，范围 1–100 |
| `--perturber-eps` | `8/255` | PhotoGuard L∞ 扰动预算 |
| `--perturber-step-size` | `2/255` | PGD 单步大小 |
| `--perturber-steps` | `10` | PGD 迭代次数 |
| `--perturber-model` | 本地模型目录 | 不接受运行时远程加载 |

`--layers` 仍决定基础层集合；为了避免“选择了扰动器但实际未执行”的误用，`--perturber noise` 和 `--perturber sd` 会自动将 `perturb` 加入最终层集合。

退出码：`0` 成功，`1` 未恢复出 payload（含盲检未找到信封），`2` 参数或运行错误。`verify` 不带 flag 时由「缺参退 2」变为「盲检 0/1」。

`protect` 会拒绝把输出写到输入文件自身（含硬链接别名），报 `refusing to overwrite the input` 并退出 2 —— 原图留底是 AGENTS.md 第五节的硬要求。写盘采用同目录临时文件 + `os.replace`，因此中断、磁盘写满或 Ctrl-C 都不会在成品路径上留下半截文件；已有文件的权限位会沿用，新文件遵循进程 umask。若输出路径是符号链接，替换的是链接本身、它指向的文件不受影响。批量处理时，同名 stem 的输入会自动得到 `_2`、`_3` 后缀，不会互相覆盖。

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

## 项目结构

```text
src/photo_guard/
├── cli.py                   # protect / verify / devices / download-models
├── gui.py                   # PySide6 桌面界面与后台批处理
├── pipeline.py              # 固定顺序编排和参数校验
├── outputs.py               # 原子写盘与批量命名（绝不写输入文件）
├── device.py                # CPU / CUDA / MPS 检测与选择
├── watermark_invisible.py   # DWT-DCT-SVD + CRC 信封盲检 + 旧版线索路径
├── watermark_visible.py     # subject / tile / center
├── subject.py               # Haar → Sobel 显著性 → 中心降级
├── perturb.py               # 扰动注册表和重依赖懒加载
├── photoguard.py            # SD VAE encoder PGD
├── compress.py              # 输出尺寸处理
├── resources.py             # 源码和打包资源定位
└── download.py              # 唯一联网的模型下载入口

packaging/
├── build_desktop.py         # Nuitka 分平台构建
├── windows-installer.iss    # Windows Inno Setup
└── create_dmg.sh            # macOS DMG
```

## 开发与测试

```bash
# 核心开发环境
uv sync --frozen --group dev

# GUI 开发环境
uv sync --frozen --group dev --extra desktop

# 完整 PhotoGuard 环境
uv sync --frozen --group dev --extra desktop --extra photoguard

# 快速测试
uv run pytest -m 'not slow' -q

# CLI 帮助
uv run photo-guard --help
```

当前快速测试为 **55 项**，覆盖原有三层顺序、所有层组合、隐水印 JPEG 回环、参数校验、CRC envelope、设备发现、GUI 安全默认值和输出命名策略。

项目依赖必须写入 `pyproject.toml` 并由 `uv.lock` 锁定；禁止新增 `requirements.txt`，所有 Python 命令统一通过 `uv run` 执行。

## 桌面发布

`.github/workflows/release-desktop.yml` 在以下条件触发：

- GitHub Actions 手动运行；
- 推送 `v*` 版本标签。

Windows 和 macOS 必须在各自 runner 上构建，不能交叉生成。工作流会：

1. 使用 `uv.lock` 同步完整依赖；
2. 下载并嵌入 SD VAE；
3. 使用 Nuitka 生成 standalone 应用；
4. 执行无 GUI 烟雾测试；
5. 生成安装包/DMG 和 SHA-256 文件；
6. 上传 GitHub Actions artifact。

本地构建命令仅应在目标平台执行：

```bash
uv sync --frozen --extra desktop --extra photoguard --group package
uv run photo-guard download-models
uv run python packaging/build_desktop.py
```

## 已知边界

- 隐水印可能在大幅裁剪、多轮强压缩或全图重绘后丢失；
- **信封回环受 payload 长度与图像内容影响**：实测在噪声型测试图上，payload 超过约 18 字节后验真可能失败（纹理型测试图约 33 字节起），短 payload 亦有个别长度失败（见 `docs/fix-plan.md` P10）。请优先使用较短的 payload，并在发布前用 `verify` 自检一次；
- Haar 人脸检测对侧脸、遮挡和多人场景能力有限；
- PhotoGuard 效果依赖目标模型族，净化、未来模型或非扩散编辑流程可能绕过；
- 当前没有 Windows AMD/Intel GPU 加速、Intel Mac 包、代码签名或 Apple notarization；
- 项目尚未建立针对主流社交平台的自动化上传/下载压缩基准。

## 参考

- `AGENTS.md`：原始三层方案和 uv 环境规范；
- `CLAUDE.md`：开发代理约束和架构说明；
- `invisible-watermark`：频域水印实现；
- MIT PhotoGuard：对抗图像编辑思路。

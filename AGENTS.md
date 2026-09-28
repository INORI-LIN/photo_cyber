# 照片防盗用方案：明水印 + 隐水印 + PhotoGuard

> 三层叠加，覆盖「直接盗图搬运」与「AI 二次生成（改图/换脸/去水印）」两类威胁。
> 定位：抬高盗用成本 + 万一被盗能确权，并非 100% 物理阻止。

---

## 一、方案构成与分工

| 防护层 | 作用 | 主要针对 |
|--------|------|----------|
| **明水印** | 给人看，让随手搬运者知难而退；绑定主体后擦它即毁图 | 直接盗图搬运 |
| **PhotoGuard 对抗扰动** | 误导扩散模型，让 AI 去水印/改图一重绘就崩坏 | AI 二次生成 |
| **隐形水印** | 肉眼不可见、可提取，兜底确权维权 | 两类威胁均覆盖 |

三者互补：搬运由明水印挡，AI 处理由扰动挡，万一被绕过由隐水印确权。

---

## 二、处理顺序（关键，错了会自相残杀）

```
① 隐形水印  →  ② PhotoGuard 扰动  →  ③ 明水印  →  发布
   嵌入原图        加对抗扰动            压在主体上
```

- **隐水印必须最先**：要嵌进相对干净的原图频域；先加扰动/明水印会污染载体，降低提取成功率。
- **PhotoGuard 在中间**：扰动针对图像内容计算，先打明水印会干扰其分布、削弱效力。
- **明水印最后压上**：给人看的，放最后不影响前两层。

> 常见错误：先打明水印再加扰动 → 扰动效力明显下降。

---

## 三、各层技术细节

### ① 隐形水印（最先执行）

- **算法**：选**频域**方案（DWT-DCT），抗压缩、缩放、轻度裁剪；**不要用 LSB 最低位**嵌入（一压就没）。
- **工具**：开源 `invisible-watermark`（Python）；进阶可用深度学习方案（HiDDeN、StegaStamp 思路）鲁棒性更强；商业 Digimarc、Imatag。
- **嵌入内容**：唯一 ID / 署名信息。
- **强度**：因后续有平台压缩，嵌入强度适当调高。
- **弱点**：若对方做整图全重绘，像素被大幅改写可能丢失 → 由第②层扰动配合兜住。

### ② PhotoGuard 对抗扰动（中间执行）

- **原理**：加入肉眼几乎无感的微小噪声，误导扩散模型，使任何 inpainting / 重绘（去水印、改图、换脸都属此类）输出崩坏、失真。
- **工具**：
  - **PhotoGuard**（MIT）—— 直接破坏 AI 图像编辑，最对症。
- **局限**：针对特定模型族，新模型或「先净化扰动再处理」（如 DiffPure 思路）可能绕过；平台压缩会削弱强度。它是**降低成功率、提高成本**，非物理屏障。

### ③ 明水印（最后执行）

- **绑定主体**：不要只放角落（易裁剪、易被 AI 定位擦除）。半透明压在**脸部/主体关键纹理**上，或**全图平铺低透明度网格**（5%–15%）。
- **混合模式**：用叠加（overlay）/正片叠底，使水印随画面变化，难被算法当独立图层分离。
- **原理**：AI 去水印靠「周围干净像素脑补」，水印与主体交织后，擦它=重绘整张脸=毁图。
- **工具**：手机端「水印相机」「Photo Watermark」；桌面端 Photoshop / GIMP；或脚本（Pillow）。

---

## 四、必须避开的坑

1. **平台二次压缩是最大杀手**：上传后平台强制重压会同时削弱扰动与隐水印。
   - 应对：隐水印用抗压缩频域算法、强度调高；**自己先按平台规格压一遍再处理**，让成品即为「压缩后状态」，减少平台再压破坏。
2. **顺序不能错**：严格按「隐水印 → 扰动 → 明水印」（见第二节）。
3. **扰动非永久**：针对现有模型，新模型可能绕过——这是组合方案的固有边界，需接受。

---

## 五、落地 Checklist

- [ ] 发布前原图长边压到约 1080px，画质适度降低
- [ ] 嵌入抗压缩隐形水印（`invisible-watermark`，DWT-DCT）
- [ ] 对在意的照片加 PhotoGuard / Fawkes 对抗扰动
- [ ] 打绑定主体的半透明明水印（最后一步）
- [ ] 按平台规格预压缩后导出成品
- [ ] 原图 RAW 留底备用

---

## 六、环境管理规范（强制）

为保证依赖可复现、版本受控、且不污染系统环境，本方案的脚本与工具链**统一使用 [uv](https://github.com/astral-sh/uv) 进行 Python 环境与版本管理，严禁直接使用 `pip` / `pip install`**。

### 6.1 硬性规则

1. **禁止裸用 pip**：禁止 `pip install`、`pip3 install`、`python -m pip install` 等任何直接调用 pip 的命令（无论全局还是当前激活环境）。
2. **禁止污染系统/全局环境**：所有依赖必须安装在项目本地的 uv 虚拟环境（`.venv`）中，不得安装到系统 Python 或用户全局 site-packages。
3. **Python 版本由 uv 托管**：项目所需的 Python 解释器版本由 uv 安装与锁定（`uv python install`），不依赖系统自带 Python。
4. **依赖必须锁定**：依赖写入 `pyproject.toml`，由 uv 生成并提交 `uv.lock`，保证跨机器可复现；不得手工编辑已锁定版本。
5. **统一通过 uv 执行**：运行脚本一律用 `uv run`，不手动 `source .venv/bin/activate` 后裸跑，避免环境错乱。

### 6.2 标准操作流程

```bash
# 1. 安装并锁定指定 Python 版本（示例 3.11）
uv python install 3.11
uv python pin 3.11

# 2. 初始化项目（生成 pyproject.toml）
uv init photo-guard --package
cd photo-guard

# 3. 添加依赖（uv 自动创建 .venv 并写入 pyproject.toml + uv.lock）
uv add pillow invisible-watermark numpy
#   PhotoGuard / Fawkes 等如需从源码或特定源安装：
uv add "torch" --index https://download.pytorch.org/whl/cpu

# 4. 同步环境（在新机器/CI 上据 uv.lock 精确还原）
uv sync --frozen

# 5. 运行脚本（始终通过 uv run，禁止裸跑）
uv run python protect.py input.jpg
```

### 6.3 命令映射对照（旧习惯 → 本方案要求）

| 禁止（pip 旧用法） | 必须改用（uv） |
|--------------------|----------------|
| `pip install X` | `uv add X` |
| `pip install -r requirements.txt` | `uv sync`（依赖统一在 `pyproject.toml`） |
| `pip uninstall X` | `uv remove X` |
| `python script.py` | `uv run python script.py` |
| `python -m venv .venv` + 激活 | `uv` 自动管理 `.venv`，用 `uv run` |
| 手动指定/切换 Python | `uv python install` / `uv python pin` |

### 6.4 校验与合规检查

- 提交前确认仓库包含 `pyproject.toml` 与 `uv.lock`，且**不包含** `requirements.txt`（避免诱导他人 pip 安装）。
- 可在 CI 加一道检查：检索脚本与文档中是否出现 `pip install`，命中即判失败。
- 全新环境复现验证：`uv sync --frozen && uv run python protect.py --help` 应一次通过。

---

## 七、可选：本地一键脚本流程

依赖与运行**严格遵循第六节的 uv 规范**（Pillow + invisible-watermark + PhotoGuard，禁止 pip）：

```bash
# 环境准备（一次性）
uv python install 3.11 && uv python pin 3.11
uv add pillow invisible-watermark numpy
# 运行
uv run python protect.py input.jpg
```

处理流程：

```
输入原图
  → 嵌入抗压缩隐形水印
  → PhotoGuard 对抗扰动（预留接入位）
  → 按平台规格预压缩
  → 打绑定主体的明水印
  → 输出成品
```

严格按「隐水印 → 扰动 → 明水印」顺序执行。

---

## 八、仓库实现约定

> §一–§七 为**方案规范**：定义要做什么，不随代码改动；§八–§十一 为**实现约定**：描述当前代码如何落地，随代码同步更新。

### 8.1 流水线次序与 `layers` 语义

- 唯一编排 `pipeline.protect`：`load → fit_long_edge(1080) → ① embed(DWT-DCT-SVD) → ② perturb → ③ visible → save JPEG`。
- `ProtectOptions.layers` 只控**成员**（哪些层跑），不控**顺序**（顺序写死在代码里）；`ALL_LAYERS` 是全集，CLI 暴露为逗号分隔子集。
- 空集或未知层名 → `pipeline.validate_options` 抛 `ValueError` → CLI 映射为 **exit 2**。
- **resize 先于 embed**：DWT-DCT 对几何重采样敏感，嵌入必须发生在 resize 后的像素上。这是 §二 顺序与 §五「先压长边」表面冲突的解法，勿「修回」字面顺序。
- CLI 默认 `--layers invisible,visible`；指定 `--perturber noise|sd` 会自动把 `perturb` 并入集合。扩展新层时在固定位置插入并自带成员校验，绝不让集合决定顺序。

### 8.2 两个反直觉决策（改之前先读理由）

- **`config.WATERMARK_METHOD = "dwtDctSvd"`**，不是普通 `dwtDct`：库里的 `dwtDct` 在 JPEG q≤95 就崩，SVD 变体 q≥75 仍存活。
- **载体 `CARRIER_CHANNEL=0` / `CARRIER_SCALE=72`，外加 `LEGACY_CARRIERS=((1, 36),)`**：P10 前载荷走在色度（通道 1）；4:2:0 重编码淡化色度、抹掉块投票，故移到亮度并抬高 step。载体不匹配会**打乱**读回（双向比特错误），读侧必须依次尝试候选，不得写死单一载体。`_CarrierEmbed` 另修了 `imwatermark` 的 H/V 细节带互换（P11）。

### 8.3 模块职责与可替换性

| 模块 | 职责 / 边界 | 可整体替换 |
|---|---|---|
| `pipeline.py` | 唯一编排；`_same_file` 拒绝输出路径等于输入 | 否 |
| `outputs.py` | 原子写 + 批量命名；仅 stdlib + Pillow，不得引入 Qt/torch。**输出命名只有一个实现**，由 GUI 消费；CLI 是单图输出，不经手批量命名 | 是 |
| `cli.py` / `__main__.py` | argparse → `ProtectOptions` → `pipeline.protect` | 加旗标 |
| `config.py` | 对外可调默认值（CLI/GUI 暴露项）的唯一来源；模块内部函数级默认值可留在各模块 | 是 |
| `watermark_invisible.py` | 层①。两条读取路径权威不同：CRC 信封（可判真伪）、无校验和原始路径（只是**线索**） | 是（整文件） |
| `perturb.py` | 层②。`Perturber` ABC + `_REGISTRY`；`get(name, **kwargs)` 是工厂 | 加类注册即可 |
| `photoguard.py` | 真实 SD VAE 编码器 PGD 攻击；仅以 `local_files_only=True` 读本地权重 | 是 |
| `download.py` | `download-models`；**唯一**允许联网的模块，不得扩面 | 否（刻意最小） |
| `subject.py` | 纯 cv2 三级降级：Haar 人脸 → Sobel 显著性窗 → 几何中心 | 是 |
| `watermark_visible.py` | 层③。`apply()` 分派 subject/tile/center；`_load_font` 的 TTF 路径列表**不得缩**（Pillow 位图默认字体无视 `size`） | 是 |
| `compress.py` | `fit_long_edge`；0 保留原尺寸，负数非法 | 是 |
| `device.py` | CPU/CUDA/MPS 懒发现与显式选择 | 是 |
| `gui.py` | PySide6 批量 protect/verify；工作负载必须离开 Qt 主线程 | 是 |
| `resources.py` | 源码树与打包布局（Nuitka / macOS bundle）下的资源定位 | 否 |

### 8.4 可选 extra 的懒加载契约

- core 环境（无 diffusers）**必须**能 `import photo_guard.perturb`。
- `import torch` / `import diffusers` 不得出现在模块顶层；唯一集中点是 `photoguard.py`，`device.py` 亦只在函数内按需导入。
- 重导入只发生在 `SDEncoderPerturber._ensure()`，由 `apply()` 调用。
- 缺 diffusers 时 `photoguard` 抛 `RuntimeError` 并提示 `uv sync --extra photoguard`；`cli.py` 捕获打印——**保留该路径**。

### 8.5 扩展层②的四步

子类化 `Perturber` → 可调参数默认值进 `config.py`（经 kwargs 传入）→ 在 `perturb._REGISTRY` 注册 → `cli.py` 加对应旗标。`pipeline.py` 不动。

### 8.6 依赖布局

- `.python-version` = `3.11`（由 uv 托管）。
- `pyproject.toml`：`photoguard` extra = accelerate / diffusers / safetensors；`desktop` extra = PySide6；`package` group = Nuitka；`dev` group = pytest。
- **torch 目前不在 extra 隔离之内**：它由 core 依赖 `invisible-watermark` 传递引入（core 环境同样会装上 torch）。不要把「重依赖已隔离进 `photoguard` extra」写进任何文档。

### 8.7 桌面与打包

- 图像处理必须在 worker 线程（`QThread` + `moveToThread`），**绝不**跑在 Qt 主线程。
- 打包入口 `packaging/desktop_entry.py`（支持 `--smoke-test`）；`packaging/build_desktop.py` **必须在目标 OS 上运行**（Windows x64 / Apple Silicon macOS，不支持 Intel macOS）。

---

## 九、Docker 构建约定

镜像自包含：SD VAE 在构建期烘焙进 `/app/models/sd-vae-ft-mse`，运行期设 `HF_HUB_OFFLINE=1` 等完全离线。四条不得破坏的规则：

1. 构建期的模型/包下载**只允许** `RUN ... download-models` 这一步；apt 系统依赖与 uv 二进制分别来自系统源与官方镜像（`python:*-slim` + `COPY --from=ghcr.io/astral-sh/uv:latest`），不得**新增**其他联网步骤。
2. `uv` **只能**来自 `COPY --from=ghcr.io/astral-sh/uv:latest /uv ...`；不得用安装脚本或包管理器装 uv。
3. 运行镜像设 `LANG`/`LC_ALL=C.UTF-8` 与 `PYTHONIOENCODING=utf-8`；CLI 有中文输出，针对它的 CI 断言必须**整行精确相等**，不得为绕编码问题降级为子串匹配。
4. `.dockerignore` **必须**排除 `models/` 与 `.venv/`：本地模型/虚拟环境会撑爆构建上下文，并掩盖镜像内下载步骤的 bug。

冒烟口径以 `.github/workflows/docker.yml` 为准：构建 → noise protect+verify → `--network none` 跑 `--perturber sd` 证明模型真在镜像里。注意 SD 那次产物用的是 raw payload 且未加信封（`--payload-envelope`），对它做盲检必然失败——不要照抄成断言。

---

## 十、测试与 CI 约定

- 快速档：`uv run pytest -m 'not slow' -q`（先 `uv sync --frozen --group dev`）。
- **不写死任何用例数**（总数、增量都算）；要取值现场跑 `uv run pytest --collect-only -q`。
- `slow` 现状据实：marker 已在 `pyproject.toml` 注册，但全仓当前**没有任何** `@pytest.mark.slow` 标记（`-m slow` 收集 0 例）；真实 SD 慢档尚未建立。将来要跑需 `uv sync --frozen --extra photoguard` 加本地模型（`photo-guard download-models`）。
- **快速档全绿 ≠ SD 真实路径有效**：快速档不加载 diffusers、不跑真实 SD VAE（torch 仍会随 `imwatermark` 链被导入，但不走 SD 编码器路径）。
- `ci.yml` 跑 ubuntu-latest + windows-latest 矩阵。合规检查有两道门，**都不得删**：ci.yml 的 Linux shell grep（依赖 POSIX grep，Windows 腿不跑）与 `tests/test_compliance.py`（纯 Python `rglob`，全平台经 pytest 生效）。
- `docker.yml` 构建全合一镜像并冒烟，**不推送**。用 `jlumbroso/free-disk-space` 的原因：托管 ubuntu runner 约 14GB 可用，而 torch + nvidia wheel + SD VAE 解包约 6GB，不腾空间易「no space left on device」。
- 四条 fail-loud 回归锁（动相关代码前先读它们保护的决策）：
  - `tests/test_invisible_watermark_roundtrip.py::test_embed_survives_jpeg85_and_visible_watermark` — 钉住 `dwtDctSvd`；把 `config.WATERMARK_METHOD` 改回 `dwtDct` 立即变红。
  - `tests/test_pipeline_order.py::test_protect_then_verify_round_trip` — 端到端，钉住「resize 先于 embed」；有人「修正」顺序即断。
  - `tests/test_pipeline_layers.py` — 参数化全部非空子集（另含空集 / 未知层被拒两例），钉住 `--layers`「只控成员、绝不重排」。
  - `tests/test_perturb_registry.py::test_importing_perturb_does_not_import_torch` — 钉住懒加载契约；把 `import torch` 挪进 `perturb.py` 顶层即变红（该锁先清 `sys.modules` 里的 torch 再 `reload(perturb)`，只覆盖 `perturb.py` 自身——包级 `__init__` 急加载不在其覆盖内，要锁它需另加子进程探针）。

---

## 十一、协作约定

- 分支 `main`；remote `origin → https://github.com/INORI-LIN/photo_cyber.git`。
- 提交信息沿用历史体例：`type(scope): 中文摘要` + 中文正文说明缘由；历史提交带 `Co-Authored-By` 尾注（是否添加按实际协作工具决定）。
- **未经用户显式确认不得 push**：`git push` 属于影响远端的动作，需先取得同意。
- 合规白名单：§六 规定的那串被禁安装命令字面量，只允许出现在 `AGENTS.md` 与 `README.md`（它们是规则本身的文档，两道合规门均已排除）；新文档与代码不得抄入，否则 grep 门与 `tests/test_compliance.py` 都会红。
- 维护边界：§一–§七 的改动需经用户确认；§八–§十一 随代码同步，改实现时一并更新对应条目。

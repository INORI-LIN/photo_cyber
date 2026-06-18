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

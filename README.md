# photo-guard

照片防盗用三层防护框架的可执行实现，对应 [`AGENTS.md`](./AGENTS.md) 中规定的方案与技术要求。

> 三层叠加：明水印（防搬运）+ PhotoGuard 对抗扰动（防 AI 二次生成）+ 隐水印（兜底确权）。
> 目标是抬高盗用成本与提供确权能力，不是物理上 100% 阻止。

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
├── README.md                  # 本文件
├── pyproject.toml             # uv 管理的依赖与入口
├── uv.lock                    # 锁定文件，跨机可复现
├── .python-version            # uv 锁定 Python 3.11
└── src/photo_guard/
    ├── __init__.py / __main__.py
    ├── cli.py                 # argparse: protect / verify
    ├── pipeline.py            # 顺序编排（① → ② → ③）
    ├── config.py              # 集中默认参数
    ├── watermark_invisible.py # ① 隐水印（imwatermark, dwtDctSvd）
    ├── perturb.py             # ② Perturber 接口 + Noop / Noise / SDEncoder
    ├── photoguard.py          # ② SD-VAE encoder PGD 攻击（懒加载）
    ├── watermark_visible.py   # ③ 明水印（subject / tile / center 三模式）
    ├── subject.py             # ③ 主体检测（haar → Sobel 显著性 → 中心）
    └── compress.py            # 长边 resize 至平台规格
```

---

## 环境与运行

严格遵循 AGENTS.md 第六节：**全程使用 `uv`，禁止裸用 `pip`**。

```bash
# 一次性环境准备
uv python install 3.11
uv python pin 3.11
uv sync --frozen          # 按 uv.lock 精确还原核心依赖（不含 PhotoGuard）

# 想用真 PhotoGuard SD-encoder 攻击时再加可选 extra（拉取 torch 系生态 + diffusers + accelerate，约几 GB）
uv sync --extra photoguard

# 保护一张图（三层全跑，默认占位扰动）
uv run python -m photo_guard protect input.jpg -o out.jpg \
  --payload "owner:inori-lin#2026-06-18" \
  --perturber noise \
  --visible-mode subject \
  --visible-text "© inori-lin"

# 用真 PhotoGuard 扰动（首次会下载 sd-vae-ft-mse ≈335MB；CPU 也能跑，慢）
uv run python -m photo_guard protect input.jpg -o out.jpg \
  --payload "owner:inori-lin#sd" \
  --perturber sd --perturber-steps 10 --perturber-eps 0.0314

# 从可疑图中提取隐水印做确权
uv run python -m photo_guard verify suspect.jpg --payload-bytes 26
# payload-bytes 必须等于 protect 时 payload 的 utf-8 字节数
```

`uv run photo-guard ...` 也等价（通过 `[project.scripts]` 暴露）。

### CLI 参数

`protect`：

| 参数 | 默认 | 说明 |
|------|------|------|
| `--payload` | `photo-guard` | 要嵌入的唯一 ID / 署名 |
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

## 待办 / 已知边界

- [ ] **更强的主体检测**：`haar` 漏检侧脸 / 戴口罩 / 小脸，后续可换 `mediapipe` 或 ONNX 化的 RetinaFace；多人脸场景目前只取最大框，可改为多框分别贴。
- [ ] **平台二次压缩鲁棒性**：当前 `dwtDctSvd` 在 q≥75 单次压缩可还原；社交平台多重压缩 + 裁切场景需要更高强度或重复嵌入策略，是 AGENTS.md 第四节自己点出的固有边界。
- [ ] 单元测试 / CI（含 `grep "pip install"` 合规检查）。

---

## 参考

- [`AGENTS.md`](./AGENTS.md) — 方案、技术细节、环境管理规范（uv 强制）。
- [invisible-watermark](https://github.com/ShieldMnt/invisible-watermark) — 隐水印实现来源。
- [PhotoGuard (MIT)](https://gradientscience.org/photoguard/) — 对抗扰动方案，已通过 `photoguard.py` 中的 SD-VAE encoder PGD 攻击落地。

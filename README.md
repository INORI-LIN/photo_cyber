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
| ③ 明水印（tile / center） | 给人看，与主体纹理交织，擦除即毁图 | 直接盗图搬运 |

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
    ├── perturb.py             # ② Perturber 接口 + Noop / Noise
    ├── watermark_visible.py   # ③ 明水印（tile / center 双模式）
    └── compress.py            # 长边 resize 至平台规格
```

---

## 环境与运行

严格遵循 AGENTS.md 第六节：**全程使用 `uv`，禁止裸用 `pip`**。

```bash
# 一次性环境准备
uv python install 3.11
uv python pin 3.11
uv sync --frozen          # 按 uv.lock 精确还原依赖

# 保护一张图（三层全跑）
uv run python -m photo_guard protect input.jpg -o out.jpg \
  --payload "owner:inori-lin#2026-06-18" \
  --perturber noise \
  --visible-mode tile \
  --visible-text "© inori-lin"

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
| `--perturber` | `noop` | `noop` 或 `noise`（占位） |
| `--visible-mode` | `tile` | `tile` 全图平铺 / `center` 中心区域 |
| `--visible-text` | `© photo-guard` | 明水印文字 |
| `--visible-alpha` | `0.10` | 透明度，5%–15% 区间见 AGENTS.md 三③ |
| `--long-edge` | `1080` | 长边像素 |
| `--quality` | `85` | JPEG 质量 |

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

### ② PhotoGuard 对抗扰动 — `perturb.py`

- 抽象基类 `Perturber.apply(bgr) -> bgr`，注册表 `_REGISTRY` 按名取实例。
- 内置实现：
  - `NoopPerturber`：默认，原样返回，对应 AGENTS.md 三② 原话「预留接入位」。
  - `GaussianNoisePerturber(epsilon=2/255)`：ε-bounded 噪声，肉眼无感的占位实现，证明该层确实在 pipeline 上跑通。
- 接真 PhotoGuard 时只需新增一个 `SDEncoderPerturber(Perturber)` 并注册到 `_REGISTRY`，pipeline 与 CLI 都不用改。

### ③ 明水印 — `watermark_visible.py`

- 后端：纯 `Pillow`（不引入 OpenCV 仅为这一步加复杂度）。
- 两种模式：
  - `tile`：低透明度文字网格，按 `gap` 间距 + 30° 旋转铺满全图，与主体纹理交织；
  - `center`：半透明文字压在画面中心 60% 区域，是「绑定主体」的简化版（不做人脸检测）。
- 合成：`Image.alpha_composite`，语义接近 AGENTS.md 三③ 提到的 overlay。

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

## 待办 / 已知边界

- [ ] **真 PhotoGuard 接入**：当前 `perturb.py` 只有 noop / noise 占位。计划中的 `SDEncoderPerturber` 需要 `torch` + `diffusers`，按 AGENTS.md 第六节用 `uv add torch diffusers --index https://download.pytorch.org/whl/cpu` 引入；GPU 环境上才有合理速度。
- [ ] **明水印「绑定主体」的真实版**：现 `center` 模式按图像几何中心粗略放置；接入人脸 / 显著性检测后才是 AGENTS.md 三③ 描述的「压在脸部 / 主体关键纹理上」。
- [ ] **平台二次压缩鲁棒性**：当前 `dwtDctSvd` 在 q≥75 单次压缩可还原；社交平台多重压缩 + 裁切场景需要更高强度或重复嵌入策略，是 AGENTS.md 第四节自己点出的固有边界。
- [ ] 单元测试 / CI（含 `grep "pip install"` 合规检查）。

---

## 参考

- [`AGENTS.md`](./AGENTS.md) — 方案、技术细节、环境管理规范（uv 强制）。
- [invisible-watermark](https://github.com/ShieldMnt/invisible-watermark) — 隐水印实现来源。
- [PhotoGuard (MIT)](https://gradientscience.org/photoguard/) — 对抗扰动方案，将作为 `perturb.py` 真实实现的接入目标。

# Efficacy matrix（bench）

测两件此前只有承诺、没有数字的事，输出可复现的 CSV；**运行在 core 环境**（noise 档不需要
torch/diffusers；脚本顶层不 import 它们）。

1. **隐水印抗重编码**：每格产物用 CRC 信封判定 `pass`（与 `verify` 同权威）。
2. **扰动残存比例**：`rms_ratio` / `linf_ratio` = 扰动在重编码链后**还剩多少**（分母 = 同一
   张图的 `identity` 格，故 `identity` 恒为 1.0）。**它量的是「扰动还剩多少」，不是「保护还剩
   多少」**——任何场合都不得写成「防护强度」。

## 运行

```bash
uv sync --frozen --group dev
uv run python bench/efficacy_matrix.py --out-dir /tmp/pg-bench --perturber noise
# sd 档（需要 `uv sync --extra photoguard` + 本地模型；见下文「sd 档口径」）：
uv run python bench/efficacy_matrix.py --out-dir /tmp/pg-bench --perturber sd
```

产物：`cells.csv`、`retention.csv`、`summary.md`（外加 `artifacts/` 可供人工抽查）。
不加 `--images-dir` 时用确定性合成语料（`textured_detail` / `portrait_like` / `smooth_lowtex`，
各 1080×810，固定种子）；给 `--images-dir` 则读该目录（需 ≥256×256）。

## 冻结契约（P5 引用此表；脚本会自校验表头，漂移即退 2）

`cells.csv` 列（顺序即契约）：

`image, cell, ops, artifact_subsampling, stored_payload_bytes, bits, blocks_per_bit,
carrier_channel, carrier_scale, fixture_sha256, fixture_w, fixture_h, pass, crc_ok,
payload_match`

`retention.csv` 列：`image, cell, rms_ratio, linf_ratio`。

- `pass = crc_ok AND payload_match`，由 `watermark_invisible.extract_envelope` 派生（CRC 是唯一
  权威）；`crc_ok` 与 `payload_match` 分列便于定位失败形态。
- `blocks_per_bit = ((H // 4 * 4) // 8) * ((W // 4 * 4) // 8) / bits`
  （默认 1080×810、16 B payload → 296 bit、135×101 块 → 13635/296 = **46.0642**；该值是「结构
  上界」的余量，不是可靠性阈值——可靠性由成品自检承担，见 `docs/fix-plan.md` §10.14）。
- `ops` 逐字记进 CSV（`repr` 形式）；`artifact_subsampling` 记实际产物的 JPEG sampling 因子。

## 12 格与 ops 语义

| cell | ops |
|---|---|
| identity | （无） |
| jpeg_q90 / q95 / q85 / q75 / q60 / q50 | `jpeg=quality, subsampling=2, optimize=True` |
| q75_x2 | 同 q75 两次 |
| webp_q80 | `webp quality=80, method=4` |
| downscale_720 | `scale_long=720`（`compress.fit_long_edge`） |
| downscale_720_back_1080 | `scale_long=720` → `scale_to=1080`（LANCZOS 放大回长边 1080） |
| combo_repost | `scale_long=720` → `jpeg 75` → `jpeg 85` |

**被测对象是「重编码后的产物」**：每格把 ops 结果落盘到 `artifacts/`，`pass`、格式/长边检查
都读那个文件（首版曾误读 ops 前的产物——被 P4 自检保证必可读，使钉住行空转；复核发现后已修）。
ops 链的编码语义：几何 op 先作用于像素、由**下一个**编码器落盘（`scale_long→jpeg 75` 只编码一次
@75）；纯几何链由末尾的 JPEG 默认编码收尾（q85/subsampling 2/optimize，即「平台重存」）。
`blocks_per_bit` 以**产物（ops 前）**几何计算（水印嵌在那里）；`artifact_subsampling` 描述被测的
**ops 产物**。

**钉住行**：只有 `textured_detail` 的 `identity` 与 `jpeg_q85` 要求 100%；其余格是观测值，
首轮 `<100%` 属产品发现（走 Q2 决策，禁缩语料、禁降钉）。

## 退出码

- `0`：钉住行 100%、负向控制正确（仅 visible 层产物必须判定失败）、行数
  `len(images) * len(CELLS)`、**ops 产物**的格式与长边符合 ops、`blocks_per_bit ≥ 8`、
  每张图的 identity `rms_ratio` 精确 1.0、identity 扰动非空。
- `1`：钉住行未 100%，或负向控制假阳（visible-only 竟能验真）。
- `2`：环境/契约不可用（缺 SD 模型、Pillow 无 webp、图 <256×256、表头漂移、ops 产物尺寸/格式
  不符、`blocks_per_bit < 8`、identity 扰动为零）。

> 计划里的「反向配对 `abs(rms_ratio-1.0)>0.1`」**未按字面实现**：以 identity 为分母时该值恒为
> 1.0，而要求每个格子的扰动都退化 >10% 并非设计保证。落地的对应保障是「每张图 identity 精确
> 1.0」＋「扰动为零即退 2」＋summary 的逐格敏感性面板（见 `docs/fix-plan.md` §10.14 登记）。

## 自证失败法（G1 后口径）

`WATERMARK_METHOD=dwtDct` 的自证法**已失效**（G1 后非 `dwtDctSvd` 由 `_require_method` 直接抛错，
退 2 而非产出低分）。可用的两种：

- **读端降级 + 绕过自检**（推荐的脚本级自证；实测可复现）：临时把读端载体候选降级为只认
  legacy `(1, 36)`，同时把 `pipeline._verify_output` 置空（模拟 P4 之前的产物），重跑 bench ——
  钉住行应为 `pass=false` 且脚本退 **1**；还原后恢复 0。
  （副产品：不绕过自检时，P4 的成品自检会在 protect 阶段就拦下该场景并退 2——纵深防御成立。）
- **注入损坏 fixture**：对 `--images-dir` 里的一张图额外重压缩/裁剪后再跑，观察对应格失败。

**不得**因为手法变化而放宽钉住断言。

## sd 档口径

- 需要 `uv sync --frozen --extra photoguard` 与本地模型（`uv run photo-guard download-models`）。
- P1 起 PGD **有 seed**（`config.PHOTOGUARD_SEED=0`，每次 `attack()` 内新建 Generator；**字节复现只在 CPU/float32 承诺**）。`sd` 仍只作 **CI 外单次证据**，必须记录版本/参数与 `--device cpu`，**不得**把任何比值当门禁。
- CI 每周跑的是 `noise` 档（`.github/workflows/efficacy.yml`）；真 SD 的自动化断言在 `docker.yml` 的慢档步（`pytest -m slow`）。

## Spike A 首轮（2026-10-10）

P5 的人工 spike，按**直连可执行版**执行（bench CLI 零改动；其无 `--device` 旗标）。方法：3 张合成纹理图（1600×1200；protect 缩放到长边 1080 → 1080×810，等价登记）、`--perturber sd`、`--perturber-steps 10`、`--device cpu`、默认 ε=8/255、payload `photo-guard`（raw）、seed 0（P1）；对照臂 = `noise` ε=0.0。三图结果确定性一致（CPU/float32）：

| 图 | `linf_before` | `linf_after` | 非零占比 | low.max / high.max / FFT(低÷高) | `corr(res, δ)` | 潜下降（前 → 后） | `latent_ratio_saved` | SOF |
|---|---|---|---|---|---|---|---|---|
| 0 | 8 | 57 | 99.9% | 18.7 / 43.9 / 0.198 | 0.427 | 0.366 → 0.241 | 0.658 | 4:2:0 |
| 1 | 8 | 49 | 99.9% | 19.5 / 33.9 / 0.196 | 0.428 | 0.368 → 0.240 | 0.652 | 4:2:0 |
| 2 | 8 | 53 | 99.9% | 19.2 / 38.4 / 0.197 | 0.427 | 0.363 → 0.245 | 0.676 | 4:2:0 |

读数说明（**不要照抄成门禁**）：

- `linf_before = 8`：PGD 饱和 ε 预算（与设计一致）；原失败判据「`linf_before` 恒 0」未出现。
- **「低频 ≫ 高频」不成立**：交付差异的 FFT 低频带能量 ≈ 高频带的 0.20，max 分带也是高频更大（q85 量化翻转噪声主导）——与 fast 用例的 Step-0 结论同向。
- `corr(res, δ) ≈ 0.43`：交付差异与预保存扰动显著相关（噪声臂只有 ≈0.06–0.25），即 SD 的 δ 没被擦掉，是以「叠加翻转噪声后被放大」的形态残存（max 8 → 49–57）。
- `latent_ratio_saved = (1 − norm(pert)后/norm(clean)后) ÷ (1 − norm(pert)前/norm(clean)前) ≈ 0.66`：攻击自身的潜下降约 0.37、交付后剩约 0.24，**约 2/3 的效应穿透保存路径**；该值落在 P5 闸门两阈值（≥0.9 / ≤0.5）之间，**未触发任何分支**。
- 用时：单图 ~58–73 s（CPU、steps=10，首图含模型加载）。测量为仓外一次性脚本（直连 `pipeline` + 新 `latent_norm`），不入仓。

## 与容量/最小尺寸的关系

- 写侧预检只拒「结构上界装不下」（`max_stored_bytes`），可靠性由 `protect` 末尾的成品自检
  承担；二者口径与实测边界见 `docs/fix-plan.md` §6 P4 与 §10.14。
- **长边 <480 是经验线**（实测 480 全过、384 已出现 REJECT），不是预检门：失败会由成品自检
  响亮报错（退 2），消息区分「容量不足」与「内容/尺寸退化」。

## 备注

- 每周 workflow 由 GitHub 调度；仓库长期无活动时平台可能自动停用定时任务（保留
  `workflow_dispatch` 手动入口）。
- 本目录（含本文件）在两道「禁令字面量」扫描门覆盖范围内：不得出现被禁安装命令字面量、
  不得出现 `requirements.txt`；`bench/results/` 已被两个 ignore 文件排除。

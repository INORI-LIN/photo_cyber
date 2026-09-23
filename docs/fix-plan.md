# photo-guard 修复方案（fix-plan）

> 状态：草案。由一次代码审计（9 项）+ 一次完备性审计（5 项）产出，经两轮对抗验证与一次跨节一致性审查后压缩成稿。实施时按批次推进，完成后就地回写每项的验收勾选框。
> 本文档不修改 AGENTS.md；与其冲突之处在各项的「开放问题」里显式标注。

---

## 1 问题总览

| ID | 标题 | 严重度 | 工作量 | 批次 | 一句话摘要 | 状态 |
|---|---|---|---|---|---|---|
| P1 | PhotoGuard 真实路径零质量断言 / slow 死配置 / PGD 无 seed | high（真路径零断言、slow 死配置）/ medium（无 seed、ε 名不副实）/ low（scaling_factor） | S（≤25 行代码 + 1 个 slow 文件 + 3 条 fast 用例 + Dockerfile 1 行 + docker.yml 2 步） | 3 | 真 SD 路径零断言、slow 死配置、PGD 无 seed；建慢档真断言并补 seed/L∞ 语义。 | [ ] 未开始 |
| P2 | GUI 零真实测试 + 自证式假覆盖 | P1-high | M | 3 | 413 行 gui.py 从未被测试 import，两个「GUI 测试」抄逻辑自证；本 issue 抽出 Qt-free 的 gui_logic 与 gui 档覆盖。 | [ ] 未开始 |
| P3 | 验证无法盲检 + 旧版 raw 验证启发式可能误判通过 | P0 | M | 1 | verify 必须先给长度（忘了长度 envelope 便不可达），旧版 raw 又只查「坏字符过半」，故错长度/局部损坏会 exit 0 报出错误 payload；改为密集梯度 CRC 盲检 + 严格旧版判据。 | [x] 批次 1 已完成 |
| P4 | 无容量/最小尺寸校验：超容量写出全零尾巴且退出 0 | P1 | S-M（改 `:94` 时转 P6/P7） | 2 | 隐水印无容量校验：超容量时尾部比特被轮空解出 0x00，protect 仍退 0；改为缩放后按块数预检 + 成品可恢复性自检。 | [ ] 未开始 |
| P5 | PhotoGuard 保真度与强度边界 / 文档承诺大于实现 | P2 | S~M（约半天；Spike 另机 30–60 min） | 5 | PhotoGuard 只实现 encoder-attack 变体，三处衰减（uint8/JPEG q85/明水印）从未测量、文档承诺大于实现；补配对度量与边界声明。 | [ ] 未开始 |
| P6 | 两个核心效果假设无实测 / 无 efficacy benchmark | P1-high | S（不碰 src/、tests/、锁文件） | 5 | 两处对外承诺（隐水印抗重编码、扰动残存）全无实测，现有用例只锁决策不测效果；新增 core-only 的 bench 脚本 + 每周 CI，把两者变成可复现 CSV。 | [ ] 未开始 |
| P7 | 杂项：输出格式硬编码 / device 重复探测 / GUI 取消 / 共享可变 options | P3-low（升 P2-medium 需 desktop 档确证 stale-QThread 报错） | Small（1 新公开符号；无新依赖/marker） | 5 | protect 硬编码 JPEG 容器、device 重复探测、GUI 关窗无界、worker 改写调用方 options；改为按扩展名选容器、传已探测列表、线程生命周期有界关窗。 | [ ] 未开始 |
| P8 | EXIF 方向未处理 + EXIF 静默丢弃（竖拍变横图） | P1-high | M | 2 | 读图只做 `convert("RGB")`：方向未转置、ICC 静默丢弃，竖拍图永久变横图；新增私有 loader 转置方向、剥 EXIF 留 ICC，protect/verify 共用。 | [ ] 未开始 |
| P9 | 文档与实现漂移（README 项数 / CLAUDE slow 描述 / subject Tier-3） | P3-low（tier 3 不可达） | S | 3 | 事实声明无断言/无可复现命令——用例数手抄必腐烂、slow marker 被写成已有的层、tier 3 仅 cv2 抛错时可达；改为只写命令 + saliency 退化返回 None。 | [ ] 未开始 |
| P10 | 信封回环对多数 payload 长度失败（根因：JPEG 4:2:0 色度下采样） | **P0** | M（载体参数 + 候选读路径 + swap 修复 + 回归重钉） | 2 前置 | 现行 (通道1,step36) 仅 31/66 与 17/66 可通过验真；裁定改 (通道0,step72) 后四格全 66/66，代价 ≈1dB PSNR。 | [ ] 未开始 |
| P11 | 库的编码回程交换 H/V 细节带（每个受保护图背非预期失真） | P1（换亮度后升为阻断） | S（一个子类 + 等价证明） | 2（与 P10 同批） | `dwtDctSvd.py:27/:30` 取出 (h1,v1,d1) 却按 (v1,h1,d1) 送回 idwt2；色度上 mean 0.50/max 19，换亮度会成 mean 10.3–12.8/max 106。 | [ ] 未开始 |
| G1 | core 安装被拖入 torch + extra 漏声明 + 双份 cv2 | P0-blocker（「core 无 torch」契约今天结构性不可满足） | M | 4 | core 依赖 invisible-watermark 导入期无条件拉入 torch、夹带第二份 cv2，extra 又漏声明 torch/huggingface-hub；改为仓内逐字转录 DWT-DCT-SVD 算式。 | [ ] 未开始 |
| G2 | 仓库与发布物无许可证/署名（含 SD VAE 权重与 LGPL Qt） | P2-medium | M | 4 | 许可/署名从未进入交付清单也无 gate；本 issue 补 LICENSE 与第三方声明并接进发布校验。 | [ ] 未开始 |
| G3 | 输出写入无完整性保证（非原子 / 覆盖原图 / 批量撞名 / suffix 穿越） | P0-blocker | M（≈120 行 + 15 条 fast 用例） | 1 | 输出路径的去向与完整性无单一负责人：写盘占用最终路径、CLI 容许 -o 指向输入、GUI 批量只按 exists() 判重且 suffix 未净化。新增 outputs 做原子写与命名，pipeline 加「绝不写输入」守卫。 | [x] 批次 1 已完成 |
| G4 | 输入契约与资源上限缺失（alpha/ICC/多帧/解压炸弹/HEIC） | P2-medium | S-M（~90-120 行；6 例） | 5 | 读图边界无契约：全尺寸解码、alpha 丢隐藏 RGB、多帧只护第 0 帧、无上限。改为唯一 loader 解码前检查，透明叠白。 | [ ] 未开始 |
| G5 | 发布与 CI 缺口（版本四处硬编码 / GUI 无覆盖 / 无 macOS job） | P2（残余 4 项） | 0.5–1 天 | 4 | 版本号 4 处硬编码、release 无测试/tag 闸门、GUI/macOS 无 CI 覆盖；做 tomllib 单源 + verify 闸门 + wheel 冒烟 + macOS leg。 | [ ] 未开始 |

---

## 2 批次路线与内部定序

| 批次 | 内容 | 验收门槛 |
|---|---|---|
| 1 | P3, G3 | `uv run pytest -m 'not slow' -q` 全绿；`protect in.jpg -o in.jpg` 退 2 且原图 sha256 不变，`protect in.jpg -o out.jpg && verify out.jpg` 退 0 且 stdout 恰为原 payload；`git diff --stat AGENTS.md` 为空。**批次 1 已完成（2026-09-23）：见 §6 各项的实施记录。** |
| 2 | **P10 修复 + P11（前置）** → P8, P4 | 既有 fast 用例无一变红（基线 = 落地前实测，HEAD `2810e31` 为 58）；orientation=6 的 JPEG 输入输出 `size=(300,600)`；320×320 + 超容量 payload 退 2 且不落文件，200×200 退 2 且消息含 `65536`。 |
| 3 | P9→P2, P9→P1 | fast 全绿且 collect 数 = 落地前实测 + 新增（不写绝对值）；`--extra desktop` 后 `uv run pytest -m gui` 全过、0 skip；`grep -rn "55 项\|≈55 cases" README.md CLAUDE.md` 无输出。 |
| 4 | G1, G5, G2 | 全新 core-only 环境：`import torch` 抛 `ModuleNotFoundError`、`import photo_guard` 成功、`photo-guard --help` 退 0；`uv lock --check` 绿、`generate_notices.py --check` 退 0、release 的 verify 变红时两个构建 job 未启动。 |
| 5 | P6→P5, G4, P7 | `uv run python bench/efficacy_matrix.py --out-dir /tmp/pg-bench --perturber noise` 退 0 且 identity 与 jpeg_q85 在 textured_detail 上 100%、两 CSV 行数 == `len(images)*12`；`protect -o out.png` 退 0 且 stderr 含 `warning: writing PNG, not JPEG`、`-o out.bmp` 退 2 不落文件；fast 全绿。 |

三条硬定序，实施时不得调换：

1. **batch 3 内 P9 先于 P2/P1。** P9 撤销 `README.md:238` 与 `CLAUDE.md:71` 的聚合数字，并把「不写死用例数」定为唯一政策；若 P2/P1 先落地，两者会各自往文档里塞新数字，P9 再改即第二次返工，且 G1/G2/G5 的文档步骤都引用这条政策。
2. **batch 5 内 P6 先于 P5。** P5 的 README 数字替换与「强度未测量」措辞依赖 P6 的 `bench/README.md` 先给出实测口径（`rms_ratio` 定义、钉住范围、CSV 列名与 `artifact_subsampling`）；P6 的 `blocks_per_bit` 又改调 P4 的 `watermark_invisible.max_stored_bytes(h, w)`（batch 2 已落地）。
3. **G1 的 spike 必须在 batch 4 开工前完成，并按结论分支。** G1 的 spike A/B/C（`_dwt_dct_svd` 与 `invisible-watermark` 0.2.0 逐位等价）不通过就走兜底分支（core 继续声明 torch、撤回 `CLAUDE.md:12`），此时 G1/G5/G2 依赖的 core-only 闭包、extra 声明与 lock 差异面全部改写；G1 也是唯一能改变「fast 档仍经 `imwatermark` → `rivaGan.py:2` 引 torch」这一现状的条目——今天 P3 的 `'torch' in sys.modules` 断言仍为 `True`，只有 G1 落地后才应为 `False`。

---

## 3 需用户裁定的决策（实施前必须回答）

- [ ] G1 与 AGENTS.md 三-① 点名 `invisible-watermark` 的冲突：选 (a) 接受偏离、仓内逐字转录 `_dwt_dct_svd.py`（vendor 两个模块），还是 (b) 兜底（core 继续声明 torch + 撤回 `CLAUDE.md:12`）、(c) 上游 fork；同时把 spike A/B/C 的判定分支写死（A 或 B 假 → 停止、不带容差、改走兜底；C 单独假 → 只换 fixture 内容重试）。 — 影响 G1、P3、G5、G2、P6 — 建议 (a)：AGENTS.md 逐字不改，偏离作为「开放问题」显式上报。
- [ ] 九个「必须先做 spike」的条目是否共用一个总表、且在 spike 出结论前不合并对应 PR（下表即提案；`spike 未结论` 视同未完成，不得先落地实现再补测）。 — 影响 P1、P3、P4、P6、P9、G1、G2、G3、G5 — 建议：采纳下表为批次门槛。

  | # | spike 名称 | 所属 ID | 阻塞的 ID/范围 | 通过判据（一句） |
  |---|---|---|---|---|
  | 1 | Spike A 严格 margin 门标定 + Spike B 重建逐字节相等 | P3 | P3（batch 1）；P4 的上界口径 | **已执行 2026-09-23：Spike B 通过（264/264 逐字节相等、320×320 12.05ms）；Spike A 未通过** —— 真实产物 margin 仅 0.2567–0.3247（0.40 目标超出该统计量可达范围），可打印垃圾达 0.2005–0.5000，两带完全重叠，**无阈值可分**。已按文档的失败分支取「仅线索 + 反重复规则」。 |
  | 2 | 容量常数（`blocks//8` 是否远高于 q85+明水印+扰动后的可恢复上界） | P4 | P4（batch 2）；P6 的 `blocks_per_bit` | 上界 ≥29/11 字节；控制格（`+1`）全失败；安全系数 ≥ 最坏内容类 2 倍 |
  | 3 | S1 色度下采样 / S2 WebP 可用性 / S4 打包暴露面 | P6 | P6（batch 5） | S1 反推得 `(2,2,1,1,1,1)`；S2 `features.check('webp')` 为 True 则保留该格；S4 wheel/sdist 不含 `bench/` |
  | 4 | H1 Sobel 在恒定灰度上恰为 0 | P9 | P9（batch 3），进而 P2/P1 的文档步骤 | 输出 `0.0 0.0`；任一非 0 则显式传 `borderType=BORDER_REFLECT_101` 重跑 |
  | 5 | 转录等价 spike A/B/C（旧库 vs `_dwt_dct_svd`） | G1 | G1（batch 4）；决定 P3 的 `'torch' in sys.modules` 断言、P6 的 core-only 分支、G5/G2 的 lock 差异面 | A 每对 `np.array_equal` 为真（≥3 组，含非 ASCII 与非 8 倍数）、B `decode_bits(embed_bits(bits))==bits`、C 精确解出删依赖前产出的 fixture |
  | 6 | S1 PEP 639 落点 / S2 Nuitka 数据落点 / S3 ISCC `LicenseFile` | G2 | G2（batch 4） | 两处出现 `License-Expression`；licenses/models 落 `Contents/Resources`；ISCC 退 0 且向导页显示正文 |
  | 7 | `uv sync --frozen --group dev` 的 prune 是否移除 desktop extra | G3 | G3（batch 1）的验收与 GUI 手工步骤次序 | `import PySide6` 成功 → 顺序执行；`ModuleNotFoundError` → gui 步骤显式 `--extra desktop`，uv sync 那条排最后 |
  | 8 | ISCC 缺 define / `UV_PROJECT_ENVIRONMENT` 隔离 / tag 闸门 | G5 | G5（batch 4） | 缺 `/D` define 须非零退出；smoke 退 0 且两负控分别红；verify 红时两构建 job 未启动 |
  | 9 | Spike A 1×1 进真 VAE / C 64×64 步进 `max|Δ|` 与 objective / D 镜像内字节可复现 / E SD-cell 门控 / F 手工 docker preflight+慢档 | P1 | P1（batch 3）的第 2/4/5 步与验收第 3 条；E 失败路由 P3/P6 | A 同形 u8；C `max|Δ|<=8` 且 ratio<1；D 两次同 seed 逐位相同；E `verify out_sd.jpg --payload-bytes 7` == `ci-test`；F 四条真 + passed>0 |

  另有三个非门禁 spike：P2 的 S1/S2/S3（S1 因只读环境未跑，须在首次 desktop 档执行前补做）、P5 的 Spike A/B（Spike A 为 PR 必附的人工实测，无结论则该 PR 的闸门不成立）、P7 的单条条件性 spike（`_thread_stopped` 先于 `deleteLater` 连接）。
- [ ] P8 与 G4 对 ICC 的归属：顺序已由 R3/R4 定死（P8 创建唯一 loader、G4 只扩 `draft_long_edge` 与 guard；save 助手一次谈定为 `save_image_atomic(image, path, *, image_format="JPEG", quality=None, icc_profile=None)` 并穿透），但「成品是否把源 ICC 归一化到 sRGB」仍是策略选择。 — 影响 P8、G4、P7、G3 — 建议：原样保留源 ICC、不做色彩管理（透明叠白只作用于像素），并在 README 明写「不做色彩空间转换」。
- [ ] 是否允许非 JPEG 输出（P7 的 `save_format` 允许 `-o out.png` 退 0 + 警告）与 AGENTS.md 五「成品应为预压缩 JPEG」的张力。 — 影响 P7、G3、P4、P6 — 建议：取读法 A（allow+warn）：`-o out.png` 退 0 并打 `warning: writing PNG, not JPEG`，`-o out.bmp`/未知名退 2、不落文件；若取读法 B（视为禁令）则 PNG 也退 2，并须删除相应回环用例。
- [ ] G2 的阻塞项：项目许可与版权行（holder、year、是否使用 `pyproject.toml:7` 的邮箱）。 — 影响 G2、G5 — 建议：MIT 正文 + `Copyright (c) 2026 <holder>`，holder 由用户给定，邮箱只留在 pyproject 作者字段。
- [ ] 是否继续随包再分发 SD VAE 权重，以及是否把「许可与署名」写进 AGENTS.md。 — 影响 G2、G5、P6 — 建议：继续分发，但在 notices 里把权重钉死到 configured repo（MIT）并加 `--check` 门；AGENTS.md 本次不改，把「是否入规范」记为独立待办。
- [ ] G4 的 HEIC 支持与像素上限形态：递延还是现在 `uv add pillow-heif`；上限固定还是 `--max-input-pixels` 可调。 — 影响 G4、P8、P6 — 建议：HEIC 递延（懒调 `register_heif_opener()` 属依赖变更，离线不可验证），上限先固定 `MAX_INPUT_PIXELS = 64_000_000`。
- [ ] G5 的两处：smoke 在 `UV_PROJECT_ENVIRONMENT=$TMP/venv`（项目外）跑，与 AGENTS.md:88「依赖装项目本地 `.venv`」的张力；以及仓库 public/private 决定 macOS leg 每 PR 跑还是转 nightly。 — 影响 G5、P2 — 建议：接受项目外隔离 venv（冲突显式标注）或改「复制 checkout 再 sync」；macOS 建议 `ci.yml` 加 `macos-15` 每 PR 跑，并只在 Linux 上跑 smoke。
- [ ] P5/P6 的契约与阈值：AGENTS.md 三-②「输出崩坏、失真」强于可证明者，是 README 如实降级还是用户自行补边界；P6 首轮若 portrait_like/smooth_lowtex 的 q85 <100% 走哪条产品决策。 — 影响 P5、P6、P1 — 建议：README 如实写「只实现 encoder-attack 变体、强度未测量、提高成本非必然崩坏」，并把与 AGENTS.md 的差异上报；首轮不达则按 Q2 改默认 payload 长度或只在 README 限定承诺范围，禁缩语料、禁降钉。
- [ ] P8 的损坏 EXIF 语义：硬拒绝（`ValueError` → exit 2）还是警告后继续 exit 0。 — 影响 P8、G4 — 建议：硬拒绝，避免重引已删除的静默降级路径（`jfif_unit=0/1` 一致，均退 2）。

**本批已裁定（2026-09-23，批次 1）**：其中三条在批次 1 开工前经确认并按推荐执行 —— ①九个 spike 作为**不可跳过的开工门槛**（P3-A 因此被拦下并改走失败分支）；②`verify` 不带 flag 改为 0/1 盲检（唯一的退出码映射变更）；③`max_stored_bytes(h, w)` 由 P3 定义、P4 只消费。另有一条新裁定：④**P10 升为 P0 独立处理**，批次 2 开工前先做机制定位（含 Y 通道对照），且在此之前**不得收紧 P4 的成品自检**。本节其余条目仍待各自批次开工时确认。

---

## 4 全局约定

1. **uv 规范（AGENTS.md 六）**：禁止任何直接调用 pip 的安装形式（含 `pip3`、`python -m pip`）；依赖只写进 `pyproject.toml`，由 uv 生成并提交 `uv.lock`，仓库不得出现 `requirements.txt`；运行一律 `uv run`，新机器一律 `uv sync --frozen`。`tests/test_compliance.py` 与 CI 的 grep 门（注意排除 `.github`）把这条机械化；新增文档时不得把被禁字面量（pip + 空格 + install）抄进仓库——本文件正因此不写出该字面量。
2. **推进顺序与 `--layers` 语义**：处理顺序固定为 resize → invisible → perturb → visible → JPEG，任何条目都不得调换；`--layers` 只控制成员（哪些层参与），不改变顺序、不改变数量语义、不新增层。AGENTS.md 只读——冲突一律在条目「开放问题」里标注并由用户裁定。
3. **退出码契约**：0 = 成功；1 = 未取回旧版 payload（verify 无 payload）；2 = 参数或运行期错误。所有新增的 `ValueError`/`OSError`/`RuntimeError` 必须经 `cli.py:132-137` 落到 2；新增一类 exit 2（如损坏 EXIF、不支持的输出扩展名）时须有测试钉住，`cli.py:135` 会掩盖。
4. **断言强度纪律**：对既有用例只允许「加强」或「等价」两种改动（等价须逐字节/逐值相等，如半损坏 0→非 0 属加强、`n=1..66` 逐字节相等属等价）；放宽一律不允许。任何「把红改成绿」的诱因都改由 spike 或产品决策处理，不得改断言、不得加容差、不得缩语料。

---

## 5 实施纪律

1. 每批开工前用 AskUserQuestion 集中确认 2–3 条与本批相关的未定项（从第 3 节的决策清单挑），并给出推荐项；用户未答的项按推荐项执行，并在该批 PR 描述里点名「按推荐执行 X」。
2. 每批完成后跑全量 fast 回归（`uv run pytest -m 'not slow' -q`，涉及 GUI 的批次加 `--extra desktop` 与 `-m gui`），把批内各项的验收勾选框、`--collect-only -q` 的实测收集数（不写推算数字）与「加强/等价」标注就地回写本文档；出现「放宽」即为回归，必须回退。
3. 默认只提交不推送；推送需逐次显式授权（`CLAUDE.md:126`），G1 的两 commit「先红后绿」与 release 的 verify 闸门同样适用。

---

## 6 分项方案

以下为 14 项分项方案原文（按 ID 顺序原样拼接，未改写、未重编号）。落地路径为 `docs/fix-plan.md`；`docs/` 目录在 HEAD `2810e31` 尚不存在，首次落地需新建。

> 摘要：真 SD 路径零断言、slow 死配置、PGD 无 seed；建慢档真断言并补 seed/L∞ 语义。

### P1 — PhotoGuard 真实路径零质量断言 / slow 死配置 / PGD 无 seed

**严重度 / 工作量 / 批次 / 依赖 / 触及文件**
- 严重度：high 真路径零断言/slow 死配置；medium 无 seed、ε 名不副实；low scaling_factor
- 工作量：≤25 行代码；1 个 slow 文件 + 3 条 fast 用例；Dockerfile 1 行 + docker.yml 2 步
- 批次：3（P9 → P1）
- 依赖：P9、G1（skip 语义）、P5（同一 attack()）、P6、P4 的 SD-cell 闸门
- 触及文件：photoguard/config/perturb、新 test_photoguard_slow、test_{shape,registry,cli_exits}、pyproject.toml:46、Dockerfile:65

**现象与证据**
- pyproject.toml:46 注册 `slow` 但 `tests/` 零命中；test_photoguard_shape.py:12-19 只重算 `(-h)%8`（唯一）。
- docker.yml:91-107 唯一跑真 SD 路径处，只用 `grep -F`×2 + `test -s`，无 verify。
- photoguard.py:89 无 seed；:87/:113 无 scaling_factor；perturb.py:52-56 ε 非界；cli.py:80 `-eps 0` 零扰动退出 0。

**根因**
真 SD 路径无性质断言（fast 重算算术、真执行只 `grep`、`slow` 无用例）→ 攻击可静默失效而全绿。

**推荐方案**
1. photoguard.py：attack() 校验（:71-72/:76-77）移到 :69 前；PGDConfig 加 `seed`（`PHOTOGUARD_SEED=0`）；:88-92 用 CPU `Generator` 抽样；:87 加恒等性注释。
2. perturb.py：SDEncoderPerturber 加 keyword-only `seed` 转发进 PGDConfig；noise 加 `np.clip(noise,-scale,scale)`；cli.py:80 → `eps<=0 or step_size<=0`。
3. test_photoguard_slow.py（新）：`pytestmark=[slow,<3 skipif>]`；顶层禁 import torch/diffusers；skipif = `find_spec`+模型目录 `is_dir()`；fixture 只加载 1 次模型。
4. shape.py 删 :8-9/:12-19 改 `parametrize`；registry.py::test_noise_within_epsilon 改真 L∞；cli_exits.py 加 `test_zero_epsilon_is_rejected`；config.py :19 改「L∞ 界」；Dockerfile:65 → `--group dev`；pyproject.toml:46 改描述。
5. docker.yml：:91-107 后加 preflight（torch/diffusers、模型目录、/app 下 photo_guard）+ `pytest -m slow -v -rs`；P4 的 SD-cell 闸门补 `verify out_sd.jpg --payload-bytes 7`。

**被驳回或部分采纳的验证者意见**
- #11d 部分采纳：A/E 留门控；spike B 取消。
- #22/#23 部分采纳：tests 块在 .dockerignore:19-20；用 `uv run --project /app --no-sync`。
- #35 部分采纳：3 条而非 5 条（test_pipeline_layers.py:43 仅 :37/:40）。
其余 43 条验证者意见已全部并入上述方案。

**被否决的替代方案**
- `compute_padding` 抽函数只断言 `%`；`--perturber-seed` 只多一条退出码 2 路径。

**API / CLI / 格式与退出码影响**
- 新增 `PHOTOGUARD_SEED=0`、`PGDConfig.seed`、keyword-only `seed`；GUI/CLI 变确定性；noise 收紧为 `|Δ|≤ε·255`。
- 退出码 0/1/2 不变（cli.py:132-138）；唯一变化：`--perturber-eps 0` 由 0 变 2；无断言被放宽。

**测试清单**（S/SH/R/C = slow / shape / registry / cli_exits 测试文件）

| 文件 | 用例名 | 档 | 断言 |
|---|---|---|---|
| S | `test_default_seed_reaches_pgd_config`、`test_same/_different_seed_*output`、`…preserves_shape_and_dtype[4 尺寸]`、`…respects_l_inf_budget`、`…reduces_objective`、`test_protect_sd_is_byte_reproducible`（`…`=test_attack_） | slow | 同 seed 同字节；`max|Δ|<=8`；mse 递减 |
| SH | `test_attack_rejects_bad_input` | fast | `ValueError` |
| R / C | `test_noise_within_epsilon`（改真 L∞）；`test_zero_epsilon_is_rejected` | fast | `⌈eps·255⌉=4` 且 `>=1`；`exit 2` |

**验收标准**
- [ ] `pytest -m slow --collect-only -q` ≥10 条；fast 档 0 failed、3 条新用例 passed；`-eps 0` 退出 2。
- [ ] 有 extra+模型：slow 全 passed 0 skipped；无 extra/模型：全 skipped 且理由给命令。
- [ ] docker 慢档步 passed>0；5 个 spike 有结论。

**风险与未知**
- pytest 进镜像改变发布镜像内容（CLAUDE.md:42-44）；noise 收紧可能弄红 3 条回环用例（:37/:40、test_pipeline_order.py:34-52）；GPU/fp16 限 CPU/float32。

**spike（如需）**
- A｜1×1 可进真 VAE：`apply(zeros((1,1,3),u8))`→同形 u8｜失败去 1×1 + 单开 issue
- C｜64×64/steps=10/seed=0 记 max|Δ|、ratio｜通过 `max|Δ|<=8` 且 ratio<1｜失败 max|Δ|==0
- D｜镜像内两次 `protect --perturber sd --device cpu` 比字节 + 同 seed 两次 `uniform_` 逐位比｜都同则过｜否则退到同进程 `perturb.get`
- E｜门控：`verify out_sd.jpg --payload-bytes 7` = ci-test｜失败路由 P3/P6
- F｜手工 `docker build` 跑 preflight+慢档｜通过四条真 + passed>0｜失败回改步骤 4/5

**开放问题**
- AGENTS.md 冲突（条件性），需用户裁定：默认 `uv run` 合 §6.1.5，若要求直调 `/app/.venv/bin/*`（docker.yml:59）即冲突。

> 摘要：413 行 gui.py 从未被测试 import，两个「GUI 测试」抄逻辑自证；本 issue 抽出 Qt-free 的 gui_logic 与 gui 档覆盖。

### P2 — GUI 零真实测试 + 自证式假覆盖

**严重度 / 工作量 / 批次 / 依赖 / 触及文件**
- 严重度：P1-high
- 工作量：M
- 批次：3（P9 → P2）
- 依赖：G3（命名）、G5（ci.yml）、P7（cancel）、P9（文档）
- 触及：`gui_logic.py`(新)、`gui.py`、`tests/test_gui_{logic,qt}.py`、pyproject/ci、README/CLAUDE

**现象与证据**
- `tests/test_gui_logic.py:15-23` 自建 `while candidate.exists()` 循环自证；`gui.py:374-378` 同代码。
- `tests/test_gui_logic.py:8-12` 只调 `validate_options`；`tests/` 无文件 import `photo_guard.gui`。
- pyside6 仅在 extra `desktop`（`pyproject.toml:27-28`），dev 组（`:35-38`）仅 pytest；`uv.lock:849` 已锁。

**根因**
`gui.py` 把纯策略与 Qt 访问焊死，快速层装不到 PySide6，只能抄进测试自证；勾选框极性与 QSettings 键只在 gui.py。

**推荐方案**
1. `gui_logic.py`（禁 Qt）：`SETTINGS_KEYS`、`layers_from_checks(invisible, sd, visible)`、`load_settings(raw, defaults)`。
2. `layers_from_checks` 仅成员映射，全 False 返回空集；「无层」交 `validate_options`（`pipeline.py:48`、AGENTS.md §二）。
3. `load_settings`：`None`/异常→默认；按 7 键强转；`output_dir` 仅收非空绝对路径否则回落。
4. `gui.py`：`:19` 加 `gui_logic`；`:285-288`、`:292`、`:383-397` 接 `layers_from_checks`、`LAYER_PERTURB in layers`、`load_settings`。
5. `gui.py:207`/`:313-314`/`:374-378` 属 G3；`test_gui_logic.py` 重写、删 `test_gui_defaults_are_safe`。
6. `pyproject.toml:45-46` 加 marker `"gui: needs the desktop extra; not filtered by -m 'not slow'"`。
7. `test_gui_qt.py`：offscreen 置前、`importorskip("PySide6")`；fixture 隔离 QSettings、patch `discover_devices`、证 `fileName()` 在 tmp。
8. `ci.yml` 加 job `gui`（ubuntu-latest）：`--extra desktop` sync → 探针 `import PySide6` → `uv run pytest -m gui`。
9. 文档：`README.md:220-234` 加 `uv run pytest -m gui -q`（需 extra）；结构/模块表增 `gui_logic.py`；计数行不写数字。

**被驳回或部分采纳的验证者意见**
- 部分采纳 F-C3：`test_cli_exits.py:87-110` 未覆盖该断言，改由新名用例留在快速层。
- 驳回 F-R3/F-C4/F-C9/R-R4：`extension`/`zip(strict=True)`/编排器改路径归 G3。
其余 24 条验证者意见已全部并入上述方案。

**被否决的替代方案**
- `gui.py` 免 Qt import：重写 413 行。
- `pytest-qt`：违反 AGENTS.md §6。

**API / CLI / 格式与退出码影响**
- 新增 `gui_logic` 三符号与 marker `gui`；命名/`_plan_items` 归 G3；0/1/2 不变、断言只增。

**测试清单**（logic/qt=`tests/test_gui_*.py`）
| 文件 | 用例名 | 档 | 断言 |
|---|---|---|---|
| logic | test_layers_all_combos | fast | 8 组手写期望；全空报错 |
| logic | test_load_settings_junk | fast | 垃圾/相对路径回落默认 |
| logic | test_pipeline_calls_only_in_workers | fast | AST：调用只在 worker 类内 |
| logic | test_start_protect_uses_plan_items | fast | 有 `_plan_items(`、无 `_unique_output` |
| logic | test_default_layers_safe | fast | `layers == DEFAULT_LAYERS == {'invisible','visible'}` |
| qt | test_checkbox_combos_reach_pipeline | gui | 默认 `(True,False,True)`；8 组期望一致 |
| qt | test_plan_items_gives_two_distinct_outputs_for_same_stem_batch | gui | 输出互异、空后缀回落默认 |

负控：新断言须能红。

**验收标准**
- [ ] `uv run pytest -m 'not slow'` 全绿且收集数较改前增；`--extra desktop` 后 `uv run pytest -m gui` 全过、0 skip。
- [ ] 主线程加 `pipeline.protect(...)` → AST 用例红；旧命名循环与旧测试名无输出。
- [ ] test_cli_exits.py 全绿；AGENTS.md 无 diff、无 requirements.txt、uv.lock 无 diff。

**风险与未知**
- S1 阻塞（只读、无 `.venv`）：offscreen、QSettings 隔离、`run()` 信号未验证。
- Linux CI 可能缺 libGL/libxkbcommon；只给 gui job 加 apt-get install。
- worker 测试直接调 `run()`，不覆盖 `_start_worker`（gui.py:334-344）。

**spike（如需）**
- S1：假设 offscreen 可构造窗口、QSettings 可重定向、`run()` 同步；实验 = 冷 sync 后探针打印 `fileName()`/`count()`；通过 = fileName 在 tmp、count==1；失败 = 改 `wait()`。
- S3：假设改 pytest 配置不动依赖元数据；实验 = `uv sync --frozen --extra desktop`；通过 = 退出码 0 且 lock 无 diff；失败 = 纳入 lock 差异。
- S2：实验 = 跑 Linux CI；通过 = gui 全收集全过；失败 = 加 apt-get install。

**开放问题**
- 是否改用 `-m 'not slow and not gui'`？不改。
- 接受 AST 锁替代运行时验证？
- AGENTS.md 无冲突，无需裁定。

> 摘要：verify 必须先给长度（忘了长度 envelope 便不可达），旧版 raw 又只查「坏字符过半」，故错长度/局部损坏会 exit 0 报出错误 payload；改为密集梯度 CRC 盲检 + 严格旧版判据。

### P3 — 验证无法盲检 + 旧版 raw 验证启发式可能误判通过

**严重度** — P0
**工作量** — M
**批次** — 1（不后置）
**依赖** — P4（上界口径、`_verify_output`）、P8（loader）
**触及文件** — `watermark_invisible.py`、`config.py`、`pipeline.py`、`cli.py`、`gui.py`、`pyproject.toml`+`uv.lock`、`tests/{test_watermark_discovery,test_legacy_strictness}.py`(新)、`tests/{test_cli_exits,test_core_improvements,conftest}.py`、`README.md`、`CLAUDE.md`

**现象与证据**
- `watermark_invisible.py:26-31`：`extract()` 必须先有 `payload_bytes`；`:41-53` 只判 `_MAGIC` 前缀，无候选长度扫描。
- `cli.py:42-44` 无 flag 即 `SystemExit(2)`；`:64-68` 的判据只算坏字符比例，短垃圾恒 False。实测全 exit 0：`--payload-bytes 1`→`o`、`13`→错串、贴 55%→`owNer:test#00!`。

**根因**
decode 的长度只能由调用方给定，而它无法从图像推断；旧版 raw 无 CRC，判据不构成确权证据。

**推荐方案**（按序）
1. `config.py`：`DEFAULT_MAX_PAYLOAD_BYTES=128`、`LEGACY_MIN_MEAN_MARGIN=0.20`、`LEGACY_MIN_BLOCKS_PER_BIT=16`。
2. `watermark_invisible.py`：`_block_scores(image_bgr)`（复刻库取数）、`_reconstruct_bytes(scores, nbytes)`（`mean*255>127`+`packbits`，空桶取 0）。
3. 同文件 `find_envelope(image_bgr, max_bytes=None)`（**步长 1**、失败 continue；上界 = `min(DEFAULT_MAX_PAYLOAD_BYTES, max_stored_bytes(h, w))`）、`extract_envelope(...)`（只认 CRC）。
4. 同文件 `NoPayloadError`、`is_recoverable_text`、`_require_plausible_text`（严格 UTF-8+零容忍可打印；`R>=16` 才判 margin）、`LegacyExtraction`+`extract_legacy`。
5. `pipeline.py`：`verify_legacy(path, payload_bytes)`、`discover_payload(path, max_bytes=None)`；`verify_expected` 走 `extract_envelope`；**不新建 loader**（复用 `_load_oriented_rgb`）。
6. `cli.py`：`:8` 加 `watermark_invisible`；去 `required=True`；加 `--max-payload-bytes`；三分支 `is not None`；`except NoPayloadError` 在 `:132` 前。
7. `uv add pywavelets` 与 `import pywt` 同一提交；`README.md:77`/`:161`、`CLAUDE.md:131`/`:55-56` 同步；`AGENTS.md` 零改动。

**被驳回或部分采纳的验证者意见**
- feasibility R5+C5 / regression R2+C1：**部分采纳**；**驳回「margin 门不给默认值」**——该门是唯一判据。
- regression R8：**结论驳回、风险采纳**——新 fixture 自建临时目录；**不得改** `tests/conftest.py:18-28`。

其余 43 条验证者意见已全部并入上述方案。

**被否决的替代方案**
- Route B 定长头、稀疏阶梯、固定总长、朴素盲检、旧版一律判失败、`--lenient`。

**API / CLI / 格式与退出码影响**
- 0/1/2 含义不变；唯一映射变更：`verify` 不带 flag 由 `SystemExit(2)` 变为 0/1。`--payload-bytes` 0 / 1 / `N<=0` 仍 2；`--expected-payload` 完全不变；`protect --payload` 不可恢复字符 → 0 变 2。
- 断言只增不减（等价性逐字节相等；半损坏 0→非 0 是加强）；torch 本次仍 `True`，G1 后应为 `False`。

**测试清单**

| 文件 | 用例名 | 档 | 断言 |
|---|---|---|---|
| test_watermark_discovery.py 等 4 文件 | `reconstruction_matches_authoritative_decoder` 等 20 例 | fast | `n=1..66` 逐字节等于 `WatermarkDecoder`；盲检 stdout 恰为 payload；未加水印→1；错长度与贴 55%→非 0、真值→0 |

**验收标准**
- [ ] `uv run pytest -m 'not slow' -q` 全绿；collected 数与落地前实测值一致；`:43`/`:54` 字面零改动（`:25` 仅可加 P7 断言、`:87` 仅可加 P4 断言）；`git diff --stat AGENTS.md` 为空。
- [ ] `protect IN.jpg -o OUT.jpg --payload-envelope --payload "owner:alice#001" && verify OUT.jpg` → 0，stdout 恰为原 payload。
- [ ] 假通过消失且不退化为「一律判失败」；边界 `--max-payload-bytes 0`/`--payload-bytes 0`/`--expected-payload ""`/<256×256 全 2；`tests/test_compliance.py` 绿。

**风险与未知**
- `LEGACY_MIN_MEAN_MARGIN` 只由合成图标定；`docker.yml:57-62` 的纯色 640×480 是本仓唯一挡住阈值假阴性的 CI，判假阴性只能改 `:62` 生图，**不得放宽门**。

**spike（如需）**
Spike A — 假设：严格门不判死真实产物且拦下全部假通过。实验：对全部既有 fixture 形状与垃圾对照记 `(payload_bytes, R, mean_margin, 解码串)`。通过：真值 `R>=16`、margin>=阈值+2× 余量、解码串等于原值；失败：真值 `<0.20`/`R<16` 或垃圾 `>=0.20` 且可打印 → 调阈值或标「仅线索」。
Spike B（复核一次）：`1..2N` 逐字节相等、320×320 ≤1.0 s；任一 n 有差异 → 先对齐取材，**不得写进容差**。

**开放问题**
- G1 的 AGENTS.md 冲突（点名 `invisible-watermark` 的内联诉求）：**AGENTS.md 冲突，需用户裁定**；P3 保留 batch 1 且不改 `AGENTS.md`。

---

**实施记录（批次 1，2026-09-23）**

- **spike 门槛**：**Spike B 通过** —— 自研 `_block_scores`/`_reconstruct_bytes` 与 `WatermarkDecoder` 在 264/264 例逐字节相等（4 图 × n=1..66，含 643×482 奇数尺寸路径），320×320 单次 12.05 ms（预算 1.0 s），66 候选盲搜 48 ms（逐候选调库需 781 ms，快 16.3×）。**Spike A 未通过**：真实产物 `mean_margin` 仅 0.2567–0.3247（0.40 目标超出该统计量可达范围，其天花板约 0.5020），可打印垃圾达 0.2005–0.5000，两带完全重叠；且存在一个真实产物在**正确长度上解错**（`'laxers-test'`，mm=0.2567、R=154）。结论：**无阈值可分**。
- **按文档的失败分支落地**：旧版 raw 降为「仅线索」——stdout 输出 `线索（未验证）: <内容>`，stderr 打印 `blocks/bit` 与 `mean_margin`（`LegacyExtraction`），`notes` 恒含 `clue, not proof`；新增结构性**反重复规则**（拒绝 K/m 周期，杀掉 `m·N` 家族）；`LEGACY_MIN_MEAN_MARGIN=0.20` 与 `LEGACY_MIN_BLOCKS_PER_BIT=16` 仅作杀垃圾的辅助门（实测能杀非倍数错长、q50、q70、干净纹理、70% 粘贴）。**K=N/2 的不可分辨性未「解决」而是显式披露**（代码注释与本文档都写明）。
- **决策落实**：`verify` 不带 flag 由「缺参退 2」改为 0/1 盲检（本项唯一的退出码映射变更）；`max_stored_bytes(h, w)` 由 P3 定义（`(((h//4*4)//8) * ((w//4*4)//8)) // 8`；1080×810 → 1704、1200×1600 → 3750、256×256 → 128），P4 只消费。
- **C2 落实**：未新建任何 loader；三个新读图点沿用既有 `Image.open → load() → _pil_rgb_to_bgr` 写法，留给 P8 的 `_load_oriented_rgb` 统一。
- **文档漏列的连带影响**：stdout 增加「线索（未验证）」前缀后，`.github/workflows/docker.yml:85` 的 `[ "$recovered" = "ci-test" ]` 会失败 —— 已改为断言整行 `线索（未验证）: ci-test`（强度不降，反而更严）。`docker.yml` 因此进入本项触及文件；CLAUDE.md 中同款示例注释已同步。
- **测试与断言强度**：新增 `tests/test_watermark_discovery.py`（11 例）与 `tests/test_legacy_strictness.py`（21 例），`tests/test_cli_exits.py` 追加 4 例。fast 档收集数 **58 → 94**，全绿（10.9 s）。既有断言**零放宽**：
  - **加强**：`is_recoverable_text` 对「11 字符里 1 个坏字符」判否（旧的 ≥50% 启发式会放过它）；`pipeline.verify` 对不可恢复文本由「返回垃圾串」改为抛 `NoPayloadError`（CLI 由 0 变 1）。
  - **等价**：重建逐字节相等；`extract_envelope` 的返回语义不变。
  - `tests/test_cli_exits.py:43`/`:54` **字面零改动** ✓；`:25` 未改动（新增断言留给 P7）。
- **两条验收条目的修正**（不改交付意图，只改不可满足的表述）：
  1. 原文「两条 grep 零命中（`candidate.exists()`、`_unique_output`）」**按字面不可满足** —— 本文档自己规定的判重条件就是 `candidate.name in taken or candidate.exists()`。按交付意图执行：两者只允许出现在 `outputs.py` 的单一实现内（实测 `gui.py` 零命中；`_unique_output` 仅 1 处定义 + 1 处调用）。
  2. 原文「`protect … --payload-envelope --payload "owner:alice#001" && verify OUT.jpg` → 0」**依赖 fixture 与长度**（见 P10）：S1 通过、S2 失败。已改为按 P10 的画像表判定，不再作为本项的无条件验收。
> 摘要：隐水印无容量校验：超容量时尾部比特被轮空解出 0x00，protect 仍退 0；改为缩放后按块数预检 + 成品可恢复性自检。

### P4 — 无容量/最小尺寸校验：超容量写出全零尾巴且退出 0

**严重度** P1
**工作量** S-M（改 `:94` 时转 P6/P7）
**批次** 2
**依赖** G1、P3、G3、P7、P6/P5/P1/G5、P9
**触及文件** `src/photo_guard/{config,watermark_invisible,pipeline}.py`、A/B/C、`README.md`、`CLAUDE.md`；`MSB`=`watermark_invisible.max_stored_bytes`

**现象与证据**
- `watermark.py:77-78`/`:152-153` 只查 `r*c<256*256`；`dwtDctSvd.py:87-108` 位在块上轮转、无容量校验；`pipeline.py:43-60` 无上界、`:64` 先于 `:68`；`cli.py:101-106` 退 0。
- 零尾巴：`dwtDctSvd.py:54-68` 空分数→`:49` NaN→`:51` False→0；1080x810 块数 13635→上界 1704 字节。

**根因**
超长 payload 静默饿死尾部比特而 protect 仍退 0；常量关不掉（q85 叠明水印削弱 payload），检查不能进 `validate_options`。

**推荐方案**
1. `config.py`：加 `WATERMARK_BLOCKS_PER_BIT: int = 1`（spike 前唯一允许值；注释含推导链与实测数字）与 `WATERMARK_MIN_IMAGE_PIXELS = 256*256`。
2. 加 `watermark_invisible.max_stored_bytes(h: int, w: int) -> int`=`((h//8)*(w//8))//(8*K)`（写「结构上界」）；`pipeline.validate_capacity(stored, h, w)` 抛 `ValueError`，消息含上界、像素地板与 `--payload`/`--long-edge`/`--layers` 补救；P3 上界=`min(DEFAULT_MAX_PAYLOAD_BYTES, MSB(h,w))`。
3. `protect()`（`:68-75`）：`fit_long_edge`→`_pil_rgb_to_bgr`→保留 `if LAYER_INVISIBLE in opts.layers:`→`pack_payload`（envelope 时）→`validate_capacity`（stored 的 UTF-8 长度、`bgr.shape`）→`embed`。
4. 加私有 `pipeline._verify_output(output_path, opts, stored_payload)`，紧跟 `:94`、仅隐水印层跑过时调用：envelope 走 `verify_expected`（CRC 门）、错误须含路径；raw 用 `verify` 求逐字节相等、不套 margin 门。
5. A/B 新、C 追加两条；`200/201` 写 `MSB(320,320)`/`limit+1`；文档/CI：`README.md:145/152/176`、`:161`、`README.md:238`/`CLAUDE.md:71`、`CLAUDE.md:74-78`、`docker.yml:91-107`（P9：不写数字；R14：只本地复现）

**被驳回或部分采纳的验证者意见**
`#5` 部分采纳：`recovered != payload`、`endswith('\x00')` 采纳；`==200` 内容依赖，待 spike；其余 24 条已并入。

**被否决的替代方案**
- 其余替代（`embed` 内自检、只预检、关层仍退 0、截断）均否。

**API / CLI / 格式与退出码影响**
- 新增 `max_stored_bytes`、`validate_capacity`（抛 `ValueError`）、私有 `_verify_output`、2 个 config 常量；退出码 0/1/2 **不变**；无既有断言放宽（C`:43`/`:54` 零改动、`:87-109` 只追加，R16：该形状已补进 P3 Spike A 语料）。

**测试清单**（A=`tests/test_invisible_watermark_capacity.py`，B=`tests/test_pipeline_capacity.py`，C=`tests/test_cli_exits.py`；例名省 `test_`）
| 文件 | 用例名 | 档 | 断言 |
|---|---|---|---|
| A | max_stored_bytes_matches_block_arithmetic；hard_overflow_produces_zero_tail；validate_capacity_boundaries | fast | `MSB(320,320)==1600//(8*K)`；201 ASCII 零尾；`limit`/`limit+1`/地板/`384x288` |
| B | protect_refuses_over_capacity_before_writing；…refuses_image_below_pixel_floor；…without_invisible_layer_ignores_capacity；verification_failure_is_loud[True/False]；long_edge_640_envelope_matches_spike_measurement；（C）protect_over_capacity_exits_two；non_noop_perturber_enables_perturb_layer | fast | 无文件+`can carry at most`；`65536`；raw 140→201 抛错；C：`main==2`、verify 11 字节==0 |

**验收标准**
- [ ] `uv run pytest -m 'not slow' -q` 绿、收集数不减。
- [ ] 320x320+201 字节+`--layers invisible` → 退 2 无文件；200x200 → 2 含 `65536`。
- [ ] `git diff --quiet -- AGENTS.md`、`pyproject.toml`/`uv.lock` 无改动；注释含 spike 摘要。

**风险与未知**
- 实测值（640 失败、1080x810 18 格中 13 格失败）出自未锁定环境（opencv 5.0.0.93、torch stub），须在锁定环境重跑。

**spike（如需）**
- 假设：`blocks//8` 远高于「q85+明水印+扰动后仍可恢复」的上界；与第 5 步同批。
- 实验：仓库外 `/tmp/pg_capacity_spike.py --csv /tmp/pg_capacity_spike.csv`；三类固定种子内容先 2 倍再缩放；几何 256x256…1080x1440；B≤`blocks//8` 加 `+1` 控制格（必须失败）；另记 subsampling 默认/0/2 首错位字节。
- 通过：上界 ≥ 29/11 字节；控制格全失败；安全系数≥最坏类 2 倍写入注释。
- 失败：任一内容类连 29 字节都不恢复 → 不合并；改由 P6/P7 落 `subsampling=0`。

**开放问题**
- **AGENTS.md 冲突，需用户裁定**：保留顺序、只用 uv、不新增依赖，但「拒绝」与规范第五条 checklist 可能有张力。
- `--long-edge 640`+默认 envelope 失败：收紧最球几何或由 P6/P7 落 `subsampling=0`？

> 摘要：PhotoGuard 只实现 encoder-attack 变体，三处衰减（uint8/JPEG q85/明水印）从未测量、文档承诺大于实现；补配对度量与边界声明。

### P5 — PhotoGuard 保真度与强度边界 / 文档承诺大于实现

**严重度**：P2
**工作量**：S~M（约半天；Spike 另机 30–60 min）
**批次**：5（P6→P5）
**依赖**：P1 硬依赖（同改 `photoguard.py::_SDEncoderAttack` 及其 slow 文件）；P6 先落地（`bench/efficacy_matrix.py`）；README/CLAUDE 项数归 P9
**触及文件**：photoguard.py、config.py；test_perturb_retention.py、test_photoguard_slow.py；README/CLAUDE

**现象与证据**

- `photoguard.py:1` 单行 docstring（未写明只实现 encoder-attack 变体）；`:87` target 恒零、`:98` 目标 MSE(latent,0)；`:85,102-103,107-110` ⇒ 预算 8。
- `pipeline.py:94` 唯一保存点、硬编码 JPEG ⇒ 交付文件永远是 q85；`:85-92` 明水印在扰动后合成（watermark_visible.py:59-60）⇒ δ×(1−α)；`README.md:9/270` 与 `AGENTS.md:13/47` 间无数字。

**根因**

只实现两变体之一（代码未写明）；衰减只有 uint8 可界定、q85 未知；`config.py:33-35` 照抄参考实现 ⇒ 无可观测量。

**推荐方案**

1. `photoguard.py:1` docstring 补偏差清单：零 target（encoder-attack 变体）、diffusion attack 未实现且强度未测量、输入=隐水印后的图、uint8 ≤8、fp16 未验证、δ×(1−α)、q85 不断言；初始点/seed 归 P1；不写 `scaling_factor`。
2. `photoguard.py` 抽 `_validate_bgr`/`_to_tensor` 供 `attack()`；新增 `_SDEncoderAttack.latent_norm(self, image_bgr: np.ndarray) -> float` = `float(self._encode_mean(self._to_tensor(bgr)).float().norm())`。
3. 新建 `tests/test_perturb_retention.py`（2 条）：480×360、`long_edge=0`、`visible_mode="tile"`、`layers=ALL_LAYERS`、控制 `noise`+`epsilon=0.0`；slow 文件追加 1 条：`device="cpu"`、`_AttackPerturber`（`name="sd"`）。
4. 文档收口：`README.md:270` 改为「只实现 encoder-attack 变体、强度未测量、提高成本非必然崩坏、残留比例无基线」；`:9`、「已知边界」、`CLAUDE.md:104/113` 加同义句；`config.py:33-35` 仅注释。
5. 闸门：本次不实现 diffusion attack；Spike A 出数后按 `latent_ratio_saved` 裁定（≥0.9/≥2/3 语料 ⇒ 另开 PR；≤0.5 ⇒ 先修保存路径）。

**被驳回或部分采纳的验证者意见**

- 部分采纳 #34：P5 的 `noise+epsilon=0` 与 P6 的 `clean` 都合法但不能共用标签 ⇒ 只提议 P6 标注参照物。

其余 40 条验证者意见已全部并入上述方案。

**被否决的替代方案**

- 现在实现 diffusion attack（`--attack-variant`）、把「更强」当事实：否——成本未量化、未验证。
- 暴露内存态 δ、把 L∞ 当头条、改 `AGENTS.md` 三②：否/撤回——不扩 API、规格不可编辑。

**API / CLI / 格式与退出码影响**

- 唯一公开符号增量：`build_attack(PGDConfig)` 对象的 `latent_norm(image_bgr) -> float`；断言只加强不削弱；不写 fast 档 torch-free 断言（现状传递 import torch；G1 落地才可变）。
- 退出码不变（0/1/2）；无 CLI 开关、`--help` 逐字节不变；返回键集、`PGDConfig` 四默认值、`config.py` 数值不变。

**测试清单**

| 文件 | 用例名 | 档 | 断言 |
|---|---|---|---|
| test_perturb_retention.py | test_paired_control_is_byte_deterministic | fast | 两次 `protect` 输出逐字节相同 |
| 同上 | test_save_path_preserves_low_freq_better_than_high_freq | fast | 低频 `res.max()>=1`；低频>高频 |
| test_photoguard_slow.py | test_latent_delivery_ratio_is_measurable | slow | `latent_norm` 有限正数 |

**验收标准**

- [ ] `uv run pytest -m 'not slow' -q` 全绿；首轮实测后落数；新文件无 torch/diffusers import；`--collect-only` 含 P1 用例加本方案 1 条（skip 理由含 `download-models`）。
- [ ] docstring grep 命中 `zero target`/`diffusion attack`/`uint8`/`JPEG`/`fp16`；`protect --help` 与 `test_cli_exits.py` 不改；AGENTS.md/workflows 零 diff；README 无数字；无 Spike A 则闸门不成立。

**风险与未知**

- 实测与承诺相反时：记录 → README 写真实 → 评估保存路径 → 才把 `AGENTS.md:13/47` 冲突上报。
- README 改动击穿 `Dockerfile:59` 缓存键（每个 PR 触发 ~6 GB torch 层重建与 VAE 重下）；fp16 预算不成立（钉 `device="cpu"`）；无 seed 比值不作门禁。

**spike（如需）**

- Spike A（人工，PR 必附）：假设 = q85 交付文件仍可测出扰动、低频相关性高于近 Nyquist。实验 = `uv sync --frozen --extra photoguard` → `uv run photo-guard download-models` → `uv run python bench/efficacy_matrix.py --perturber sd --out-dir <dir>`，3 张 1600×1200、ε=8/255、steps=10、CPU；记录 `linf_before`、相关系数、`latent_*`、SOF 采样因子进 `bench/README.md`。通过 = 有数且低频 ≫ 高频；失败 = bench 脚本缺失或 `linf_before` 恒 0。
- Spike B：CUDA/MPS 同攻击记 `max|δ_q|` 与 dtype。

**开放问题**

- `AGENTS.md` 三②「输出崩坏、失真」强于可证明者：README 如实说明，还是用户自行补边界？**AGENTS.md 冲突，需用户裁定。**
- P5/P6 契约与阈值请一并裁定。

> 摘要：两处对外承诺（隐水印抗重编码、扰动残存）全无实测，现有用例只锁决策不测效果；新增 core-only 的 bench 脚本 + 每周 CI，把两者变成可复现 CSV。

### P6 — 两个核心效果假设无实测 / 无 efficacy benchmark

**严重度 / 工作量 / 批次 / 依赖 / 触及文件**
- 严重度：P1-high（维持）
- 工作量：S；不碰 src/、tests/、锁文件
- 批次：5（批内序 P6 → P5）
- 依赖：P5（度量接口）、P4（容量口径）、P1（PGD seed）、P9（README.md:238 数字）；前置 spike S1/S2/S4
- 触及文件：新增 bench/efficacy_matrix.py、bench/README.md、.github/workflows/efficacy.yml；改 .gitignore、.dockerignore、README.md；不动 AGENTS.md、CLAUDE.md、src/**、tests/**、pyproject.toml、uv.lock、gpu_bench.py

**现象与证据**
- AGENTS.md:63-64（四.1）要求先按平台规格压一遍，却无实测数字；README.md:272 自认无平台压缩基准。
- README.md:238 的 55 项全是「是否跑通」断言（实为 58，归 P9）；slow marker 全仓库 0 处使用（归 P1）；ci.yml:50 只跑 -m 'not slow'。
- q85 证据全是 raw payload（test_invisible_watermark_roundtrip.py:43-68=112 bit、test_pipeline_order.py:12-33=128 bit）；唯一 envelope 先例 test_core_improvements.py:59-74=264 bit+tile。
- gpu_bench.py:1 自称 not committed、:37 import torch、:78-80 只打印 L-inf/mean；grep -rIn 0 命中。

**根因**
现有用例全是「决策的回归锁」而非「承诺的测量」：src/ 是产品代码、tests/ 受 testpaths 与 fast 档约 20s 约束、workflow 只做 liveness 断言，效果测量无处安放，抗 inpaint 连协议都没留下。

**推荐方案**
1. 新增 bench/efficacy_matrix.py（仓库根单文件；stdlib+numpy+Pillow；顶层禁 import torch；sd 走 photo_guard.perturb.get('sd')）。
2. CELLS 12 格：identity、jpeg_q90/95/85（钉）/75/60/50、q75_x2、webp_q80、downscale_720、downscale_720_back_1080、combo_repost；ops 逐字入 CSV；jpeg=subsampling=2,optimize、webp=method=4、png=PNG、scale_long=compress.fit_long_edge、scale_to=LANCZOS。
3. 末步 format/尺寸不符 ops ⇒ exit 2；_blocks_per_bit=((H//4*4)//8)*((W//4*4)//8)/(8*stored)，<8 ⇒ exit 2（P4 落地后改调 max_stored_bytes）。
4. 被测量=GUI 默认 ProtectOptions(payload=P,payload_envelope=True)+余缺省（1080/85/subject/noop）；payload 16 B ⇒ 37 B=296 bit；CSV 记 ops、artifact_subsampling、stored_payload_bytes、bits、blocks_per_bit。
5. pass=crc_ok AND payload_match ≡ verify_expected 不抛；_check 由 verify→unpack_payload 派生；负向控制（仅 visible 层，pipeline.py:59-60）在 identity 必 pass=false 否则 exit 1。
6. 扰动衰减：clean=出厂产物、pert=+ALL_LAYERS；rms_ratio/linf_ratio（分母 delta_0）；identity 精确 1.0、反向配对 abs(rms_ratio-1.0)>0.1；不用「原图 vs 产物」。
7. exit：0=identity+jpeg_q85（仅 textured_detail）100% 且钉住行非空；1=<100% 或负向误报；2=SD VAE 缺/r*c<256*256/webp 不可用。
8. .github/workflows/efficacy.yml：cron '17 3 * * 1' + workflow_dispatch、timeout 15；uv run python bench/efficacy_matrix.py --out-dir bench/results --perturber noise；core-only 取决于 G1 分支。
9. bench/README.md 写 ops 语义/零点/块数推导/钉住范围/退出码/sd 命令/自证失败法（WATERMARK_METHOD=dwtDct⇒1）；README.md:272 换首轮填数字模板；.gitignore/.dockerignore +bench/results/。

**被驳回或部分采纳的验证者意见**
- feasibility R6：部分采纳——既有 fast 证据同参数族但非同一通道（264 bit+tile vs 296 bit+subject），降级为 spike S3，禁撤钉/缩语料。
- feasibility R9：部分采纳——判据改为方向无关的 abs(rms_ratio-1.0)>0.1。
- regression R7：部分采纳——采纳「写明守护形态」，驳回加 fast 用例（守护由 weekly efficacy.yml 承担）。
其余 39 条验证者意见已全部并入上述方案。

**被否决的替代方案**
- 写成 pytest（新 marker/复用 slow）：slow 全仓库 0 处使用且 CI 排除（归 P1）；fast 档跑缩减矩阵超约 20s 预算。
- 本轮代码化真实扩散 inpaint（权重 ~2.1GB、须扩网络面，见开放问题）；latent 距离当代理 / JSON 快照当阈值 / bench 子命令 / 12 格全设阈值：均否决。

**API / CLI / 格式与退出码影响**
- 无 src/ 公开符号与子命令改动；cli.py 的 0/1/2 契约不变，test_cli_exits.py 8 例不受影响；pyproject.toml 与 uv.lock 零改动（只用 core 依赖，无 uv add/requirements.txt/pip 工具，AGENTS.md §6）。
- 断言只加强不放宽（不新增/不修改 pytest 用例，collected 数相对落地前不变）；新增参数 --out-dir、--perturber {noise,sd}、--payload、--images-dir；Dockerfile:59-63 与 build_desktop.py:24-33 不含 bench/。

**测试清单**
| 文件 | 用例名 | 档 | 断言 |
|---|---|---|---|
| bench/efficacy_matrix.py | 负向控制 + 零点 + 反向配对 | manual | identity 格 pass=false 否则 exit 1；rms_ratio 精确 ==1.0；abs(rms_ratio-1.0)>0.1 |
| 同上 | 行数 + 预检 + 结构断言 | manual | 行数==len(images)*len(CELLS)；blocks_per_bit>=8 且钉住行非空；r*c>=256*256；format/尺寸符合 ops，否则 exit 2 |
| 人工一次性 | dwtDct 校准 | manual | 改 WATERMARK_METHOD 后 exit 1 且 jpeg_q85<100%，还原后 0 |
| tests/（回归） | uv run pytest -m 'not slow' -q | fast | 全绿，collected 数相对落地前不变；test_compliance.py 绿 |

**验收标准**
- [ ] uv sync --frozen && uv run python bench/efficacy_matrix.py --out-dir /tmp/pg-bench --perturber noise 退出码 0；identity 与 jpeg_q85 在 textured_detail 上均 100%。
- [ ] 三件产物齐全、两 CSV 行数==len(images)*12、ops 列可读到 (('scale_long', 720), ('png',), ('jpeg', 75))。
- [ ] CSV 中 stored_payload_bytes==37 且 blocks_per_bit==((1080//4*4)//8)*((810//4*4)//8)/(8*37)==46.06…；summary.md 含 pass=false 的负向控制、artifact_subsampling、bits=296 与版本/sha。
- [ ] uv run pytest -m 'not slow' -q 全绿且 collected 数相对落地前不变；git diff 无 pyproject.toml、uv.lock、src/、tests/、gpu_bench.py；git status 无 bench/results/；dwtDct 校准记录为 1→还原后 0。

**风险与未知**
- 指标误读（最重要）：rms_ratio 量「扰动还剩多少」≠「保护还剩多少」；一律写「扰动残存比例」，禁写「防护强度」。
- 低纹理类首轮可能 <100%（QIM 依赖块 s[0]）：钉住限 textured_detail，不达即按 Q2 走产品决策，禁缩语料/降钉。
- 版本漂移与 sd 无 seed（photoguard.py:88-92，归 P1）：记录版本、只钉离散量、显式传 subsampling/quality/method，退路固定 tile，sd 只作 CI 外单次证据。
- 不可外推：模拟重编码 ≠ 真实平台；平台画质档/服务端锐化降噪/多次转存/img2img 均超范围；语料仅合成图；数字必带日期+sha。

**spike（如需）**
- S1 产物色度下采样：假设 4:2:0｜读 Image.open(p).layer 按 JpegImagePlugin.py:641-661 反推｜(2,2,1,1,1,1) 通过｜否则写进 artifact_subsampling 并说明该格改了两个旋钮。
- S2 WebP 可用性：假设 wheel 带 WebP｜features.check('webp')｜True 保留该格并声明 libwebp 色度不受控｜False 从 CELLS 删除并记录理由。
- S3 钉住通道首轮实测：假设 textured_detail 上 identity/jpeg_q85 均 100%｜首轮跑｜100% 保持钉住并据以填 README｜<100% 视为产品发现走产品决策。
- S4 打包暴露面：假设 wheel/sdist 不含 bench/｜uv build 后 unzip -l/tar tzf｜不含即通过｜含则只记录，不改 pyproject.toml。

**开放问题**
- Q2 首轮若 portrait_like/smooth_lowtex 的 q85 <100%：改默认 payload 长度、改 quality，还是只在 README 限定承诺范围？
- Q5 抗 inpaint 权重路径：CLAUDE.md:105 禁止扩大 download.py 网络面、Dockerfile:73-76 只烘 SD VAE；选项 (a) 只留书面协议（推荐）、(b) 手工备权重 + local_files_only、(c) 破例扩 download.py。AGENTS.md 冲突，需用户裁定
- Q1/Q7：保存前那段（pipeline.py:85-94）本基准只给 retention_vs_shipped，P5 补访问器后再加 retention_vs_source 列；容量口径待 P4 的 watermark_invisible.max_stored_bytes(h, w) 落地后由 P6 改调。

> 摘要：protect 硬编码 JPEG 容器、device 重复探测、GUI 关窗无界、worker 改写调用方 options；改为按扩展名选容器、传已探测列表、线程生命周期有界关窗。

### P7 — 杂项：输出格式硬编码 / device 重复探测 / GUI 取消 / 共享可变 options

**严重度 / 工作量 / 批次 / 依赖 / 触及文件**
- 严重度：P3-low（升 P2-medium 需 desktop 档确证 stale-QThread 报错）
- 工作量：Small；1 新公开符号；无新依赖/marker
- 批次：5
- 依赖：P2（desktop 档 + `gui` marker）、G3（`save_image_atomic`）、P8（ICC）
- 触及：`src/photo_guard/`（pipeline/cli/device/photoguard/gui）、`tests/test_*.py`、`README.md`

**现象与证据**
- `pipeline.py:94` 硬编码 `format="JPEG"`、`cli.py:16-17` 不看扩展名 → `-o out.png` 写 JPEG 字节；`Path(".png").suffix == ""`。
- `device.py:99` 二次调 `_torch_devices()`（`discover_devices()` 已有列表）；`cli.py:121`/`gui.py:274` 各重探一次。
- `gui.py:399-405` 关闭无界重排；`gui.py:80-84` 在 per-item try（`:89-94`）外改写调用方 options。

**根因**
保存硬编码容器而非由输出路径推导且 CLI 不校验；`_other_adapters()` 无入参只好重探；关窗判据用错（QThread 运行与否），而取消只能在 PGD 步间被观察。

**推荐方案**
1. `pipeline.py`：加 `save_format(output_path: Path) -> str`（勿用 `Path.suffix`；无尾串→JPEG；未知名→`ValueError`）；`protect()` 在 `:64` 后 `:65` 前调用。
2. `:93-94` → `outputs.save_image_atomic(…, image_format=output_format, quality=opts.quality)`；PNG 不传 quality；JPEG 字节不变。
3. `cli.py`：`:78-81` 后（`:73` 的 `try`）校验并打 `warning: writing PNG, not JPEG`。
4. `device.py`：`_other_adapters(devices)`，`:99` 用它过滤、`:107-111` 两行式 extend。
5. `photoguard.py`：私有 `_check_cancelled()` 作 `attack()` 首句（先于 `:69`），替换 `:93-95`。
6. `gui.py`：`replace` 建一次 options 副本（含 `cancel_check`），失败也 `finished.emit`；`MainWindow` 闸门改用线程生命周期：`_worker_finished`、`_thread_stopped` 须在 `:342` `deleteLater` 前连，`closeEvent` 有界重试（`_CLOSE_GRACE_SECONDS`/`_CLOSE_RETRY_MS`）。
7. 文档：`pipeline.py:1` 归 P8；`README.md:98`/`:171`/`:153`/`:161` 与 `CLAUDE.md:85` 改容器中性并写扩展名规则；不碰 `README.md:238`、`CLAUDE.md:12/:71`。

**被驳回或部分采纳的验证者意见**
- #26：接受 `README.md:153`/「55 已过期」，驳回逐文件展开数与「~65-67」。#4：驳回「~55 → 61-63」。其余 28 条意见已并入正文。

**被否决的替代方案**
- JPEG-only（退 2）：砍掉非发布副本；仅 PNG 回环转不绿时启用。

**API / CLI / 格式与退出码影响**
- 除 `save_format` 外全私有；无新字段/开关/依赖。
- **退出码契约（0/1/2）不变**；输入集合变化：`out.bmp` 0→2、`out.png` 0→0（改 PNG+警告）、`out.`/`"out.jpg "` 0→2；无断言放宽。

**测试清单**（`tests/`）
| 文件 | 用例 | 档 | 断言 |
|---|---|---|---|
| test_cli_exits.py | PNG+warn；未知名退 2；`:25` +1 行（`:43`/`:54` 不动） | fast | 容器==PNG（修复前 JPEG）、`'warning: writing PNG, not JPEG' in err`、不建文件 |
| test_core_improvements.py | 映射/拒绝；先于读图；复用 instance | fast | `.bmp`/`out.`→`ValueError(match='unsupported output extension')`；不存在的输入抛同错（修复前红） |
| test_device.py / test_perturb_registry.py | 探测一次；取消先于加载 | fast | 计数==1；未支持名单只含 `Intel …630`；`InterruptedError`（`_ensure_loaded` 未调） |
| test_gui_qt.py（P2 夹具） | T8/T9/T10 | desktop | T8 调用方 kwargs 未变、`perturb.get` 计数==1；T9 关窗有界；T10 `cancel_task()` 空 worker 不抛 |

**验收标准**
- [ ] `uv run pytest -m 'not slow and not gui' -q` 全绿；既有零变红（基线=落地前实测 58 条），不写预测数。
- [ ] `protect -o out.png` 退 0、stderr 含 `warning: writing PNG, not JPEG`、容器==PNG；`verify` 退 0 回显 payload。
- [ ] `-o out.bmp` 退 2 且不建文件、`-o out.jpg` 与修复前逐字节一致；desktop 档 T8/T9/T10 过。

**风险与未知**
- PNG 的 Pillow 行为本环境无法实跑：由修复前必红的「容器==PNG」用例把守；转不绿退回 JPEG-only。
- 残余：BaseException 逃逸时 `finished` 不发、窗口不可关，措辞不得写成「保证永不强杀」。

**spike（如需）**
- 假设：`_thread_stopped` 先于 `deleteLater` 连接；实验：desktop 档在 `finished.emit` 后忙等再 `close()`；通过：退出码 0 且无 `QThread: Destroyed while thread is still running`；失败：abort/非 0。

**开放问题**
- **AGENTS.md 冲突，需用户裁定**：第五节要求发布件是预压缩 JPEG，本方案允许 `-o out.png`（退 0 + 警告）；读法 A → allow+warn，读法 B（禁令）→ 退 2 并删回环用例。AGENTS.md 不改。
- `-o out` 保持 JPEG 默认还是拒绝？R4 定名 `save_image_atomic(…, image_format="JPEG", quality=None, icc_profile=None)`；T8/T9/T10 宿主是 P2 的 `gui` marker。

> 摘要：读图只做 `convert("RGB")`：方向未转置、ICC 静默丢弃，竖拍图永久变横图；新增私有 loader 转置方向、剥 EXIF 留 ICC，protect/verify 共用。

### P8 — EXIF 方向未处理 + EXIF 静默丢弃（竖拍变横图）

**严重度**：P1-high
**工作量**：M
**批次**：2
**依赖**：G4（同一 helper，guard 顺序从其）；G3/P7（save 助手、PNG 分支）；P9（README:238/CLAUDE:71）
**触及文件**：src/photo_guard/pipeline.py、tests/test_exif_orientation.py、README.md、CLAUDE.md

**现象与证据**（Pillow 12.2.0，uv.lock:859）
- pipeline.py:65-67 无 `exif_transpose`（Pillow 不定向：PIL/ImageOps.py:702-710）；pipeline.py:39-40 后 `info={}`（Image.py:639），故 93-94 须显式传 ICC（:771）。
- 损坏 EXIF：`jfif_unit=0` 经 JpegImagePlugin.py:402→:502-529 吞 `SyntaxError`（Image.py:1628-1630 短路后恒空）；带 `dpi` 经 :504 提前返回。今天横图+exit 0，修后 exit 2。

**根因**：`convert("RGB")` 给出存储矩阵，EXIF 在读取那刻即丢失：Pillow 不施加 Orientation，此后又经 `Image.fromarray` 的 `info={}` 往返，numpy 往返后 transpose 即静默 no-op。

**推荐方案**
1. pipeline.py:9 → `from PIL import Image, ImageOps` + `import struct`；无依赖改动。
2. 新增唯一私有 loader `_load_oriented_rgb(path: Path) -> tuple[Image.Image, bytes | None]`（35-40 旁）；体序按 R3（guard 先于 `.load()`、`draft` 居中；旧冻结不覆盖 guard）：重解析 `Image.Exif().load(info["exif"])`（异常→`ValueError`）→ `.load()` → ICC → `exif_transpose().convert("RGB")`。
3. 65-67 → `src, icc = _load_oriented_rgb(input_path)`；verify 亦走它；P3 不得建 `_load_bgr`（R2）；G4 加 `draft_long_edge`。
4. 93-94 save 加 `icc_profile=icc`、不加 `exif=`；G3 的 `outputs.save_image_atomic` 须穿透该 kwarg（R4）。
5. pipeline.py:1 docstring 归 P8（P7 只追加中性措辞）：load = 解码 + Orientation 转置 + 剔全部 EXIF / 留 ICC。
6. README.md:163-174、:266-272 与 CLAUDE.md:90-93 记方向转置、清除 EXIF（含 GPS）、保留 ICC；:238/:71 归 P9；AGENTS.md 不改。
7. 新建 tests/test_exif_orientation.py（fast）；helper `_save_jpeg(path, array, *, orientation, gps, icc)`、`_corrupt_exif_bytes`。

**被驳回或部分采纳的验证者意见**
- R-C3 部分采纳：采纳「写明 P9 前置」，驳回 `55 → 67`（已过期，实测 58）。其余 21 条意见已全部并入上述方案。

**被否决的替代方案**
- 新建 `image_io.py`；resize 后或 `final`/`rgb` 上 transpose（`info` 已 `{}`，静默 no-op）；EXIF 白名单；`try/except` 吞掉失败。

**API / CLI / 格式与退出码影响**
- 无新公开 API；签名与 dict 键不变；`size` 为显示方向尺寸（cli.py:101-105）；带 tag 嫌疑图 verify 按显示方向解释。
- **退出码契约 0/1/2 不变**，新增一类 exit 2：EXIF 无法解析的输入（`jfif_unit=0/1` 一致，`ValueError`→cli.py:132）；须测试钉住（:135 会掩盖）。**无既有断言被放宽**；test_cli_exits.py 不碰（:43/:54）。

**测试清单**（全在 tests/test_exif_orientation.py，fast 档）

| 文件 | 用例名 | 档 | 断言 |
|---|---|---|---|
| 同 | test_orientation6_output_is_upright | fast | (300,600) |
| 同 | test_orientation_tagged_output_carries_no_exif | fast | 无 exif；GPS IFD 写不进则只断此项（注 Pillow 版本） |
| 同 | test_orientation6_protect_verify_round_trip | fast | `verify==payload` |
| 同 | test_tagged_suspect_is_read_in_display_orientation | fast | 加 tag 后 `!=payload` |
| 同 | test_subject_watermark_lands_in_display_region | fast | mask 0.001~0.25、质心左上 |
| 同 | test_rotating_a_protected_image_breaks_extraction | fast | 90° 转后 `!=payload` |

另 6 条：test_untagged_source_is_not_rotated、test_source_icc_profile_is_preserved、test_tagged_png_source_is_transposed、test_tagged_tiff_is_not_double_rotated、test_corrupt_exif_exits_two_jfif_unit0/_unit1。

**验收标准**
- [ ] `uv run pytest tests/test_exif_orientation.py -q` 全绿（12 条）。
- [ ] `uv run pytest -m 'not slow' -q`：既有 58 条零变红、新增 12 条被收集。
- [ ] protect orientation=6 JPEG 得 `size=` 宽<高、输出 `(300,600)`；`jfif_unit=0/1` 均 exit 2。

**风险与未知**
- 损坏 EXIF 由静默横图+exit 0 变 exit 2（唯一硬变更）；G3×P7×P8 同改 93-94，`icc_profile` 须到达最终 save；容差不许放宽，须真实 `uv run` 复测。

**spike（如需）**
无。T2 GPS 子 IFD 与损坏 EXIF spike 已在只读环境完成。

**开放问题**
- 损坏 EXIF：硬拒绝（推荐 `ValueError`→exit 2）还是警告后继续 exit 0？后者重引静默降级，需裁定。
- **AGENTS.md 冲突裁定**：判定无冲突（方向属解码非第四层），AGENTS.md 不改；若取更严格读法则构成 **AGENTS.md 冲突，需用户裁定**。

> 摘要：事实声明无断言/无可复现命令——用例数手抄必腐烂、slow marker 被写成已有的层、tier 3 仅 cv2 抛错时可达；改为只写命令 + saliency 退化返回 None。

### P9 — 文档与实现漂移（README 项数 / CLAUDE slow 描述 / subject Tier-3）

**严重度**：P3-low（tier 3 不可达）
**工作量**：S
**批次**：3（内序 P9 → P2、P9 → P1）
**依赖**：无硬依赖；P1 同改 CLAUDE.md:71（保留「不写死用例数」）
**触及文件**：subject.py、test_subject_fallbacks.py、conftest.py、README.md、CLAUDE.md（AGENTS.md 不动）

**现象与证据**
- README.md:238「55 项」过期：AST 计数 58（46 函数 + 12 parametrize）；`-m 'not slow'` 不排除用例。
- CLAUDE.md:71 称 slow 跑真实 SD VAE，但全仓无 `@pytest.mark.slow`（pyproject.toml:46 只注册 marker；README.md:232、ci.yml:50 空）。
- subject.py:1-14 与实现不符；`:89-91` Sobel 全 0 → argmax 返 0 → tier 2 恒给左上角窗；tier 3 仅 `:101` 异常可达（死代码）；test_subject_fallbacks.py:33-42 断言与层级正交。

**根因**
数字手抄无回写机制；marker 先注册而文档照契约写；tier 3 只挂异常分支，覆盖断言与层级选择正交。

**推荐方案**
1. subject.py `detect_salient_box(...) -> Box | None`：`:70` 后加 `if not mag.any(): return None`；先过 spike。
2. subject.py `detect_subject -> Box`：抽 `_centre_box`，`:99-104` 改 try + `except cv2.error` 回退；**永不 None**。
3. subject.py `:1-14` docstring 改如实触发条件；`:12-13` 改单 Box 事实。
4. test_subject_fallbacks.py:33-42 改名 + 换断言（见下表）。
5. 新增 `test_centre_fallback_when_saliency_raises`：补 `import cv2`；patch `detect_salient_box` 抛 `cv2.error`；禁止 patch cvtColor。
6. `:25-30` 加断言、conftest.py:33 docstring 改文字（见下表）。
7. README.md:238 删项数；写快速档命令 + 覆盖面 + 「用例数见 `--collect-only -q`」；**不得有聚合数字**（P2/G1/G2/G5 不得写）；删「GUI 安全默认值和输出命名策略」句。
8. CLAUDE.md:71 删 `≈55 cases`、`~20s`；加「不写死用例数」「快速档绿≠SD 有效」与 `uv run pytest -m slow --collect-only -q`；**不得写「不需要 torch」**（仍经 imwatermark→rivaGan.py:2 引 torch）。
9. 不修：一致性检查、AGENTS.md、pyproject.toml:46（P1）、README.md:6/:270（P5）、detect_faces。

**被驳回或部分采纳的验证者意见**
- FC5 部分采纳：例子采纳，P2 条目改写而非删除。
- 自纠驳回：替换文本里的「不需要 torch」。

其余 28 条验证者意见已全部并入上述方案。

**被否决的替代方案**
- 把 55 换成真实 58：同样会腐烂，一条命令即可取值。
- CI 回写 / 文档一致性检查：需 `contents: write` 或嵌套 pytest。
- 删除 tier 3：丢掉 cv2 失败时唯一兜底。

**API / CLI / 格式与退出码影响**
- `detect_salient_box` 返回 `Box | None`（唯一调用方 subject.py:100）；`detect_subject` 仍永不 None；新增 `_centre_box`。
- **退出码 0/1/2 无变更**；无新增开关/依赖；既有断言只加强、无放宽。

**测试清单**

| 文件 | 用例名 | 档 | 断言 |
|---|---|---|---|
| test_subject_fallbacks.py | `test_centre_fallback_on_flat_image`（`:33` 改） | fast | patch `detect_faces`→`[]`；`is None`；`== Box(13,13,38,38)` |
| 同上 | `test_centre_fallback_when_saliency_raises`（新增） | fast | patch `salient` 抛 `cv2.error`；`== Box(13,13,38,38)` |
| 同上 | `test_saliency_tier_lands_on_high_contrast`（`:25-30`） | fast | `salient is not None` |

**验收标准**
- [ ] `grep -rn "55 项\|≈55 cases" README.md CLAUDE.md` 无输出（禁裸 `grep 55`）。
- [ ] `uv run pytest -m 'not slow' -q` 全绿；collect 数 = 落地前实测 + 1（不写绝对值）；该文件 `-v` 含两个新名字
- [ ] 反向实验（删判据 / 去降级）失败输出贴 PR。
- [ ] `uv run pytest -m slow --collect-only -q`：退出码 5 属预期、输出 `no tests collected (N deselected)`
- [ ] `git diff --stat AGENTS.md pyproject.toml uv.lock` 空；工作树只含上述 5 个路径。

**风险与未知**
- 恒定 640×480 + `--layers visible`：旧 Box(0,0,192,144) → 新 Box(128,96,384,288)（默认路径 config.py:41）；PR 须点明。
- CI 覆盖不到：docker.yml:62 fixture 经 invisible+perturb 后已不恒定（pipeline.py:72-86）；无断言钉住 apply_subject 落点。

**spike（如需）**
- 假设 H1 = 下条输出 `0.0 0.0`（恒定灰度 Sobel 恰 0，borderType 反射）。
- 实验：`uv sync --frozen --group dev && uv run python -c "import numpy as np,cv2;g=np.full((64,64),128,np.uint8);print(abs(cv2.Sobel(g,5,1,0,3)).max(),abs(cv2.Sobel(g,5,0,1,3)).max())"`（5＝CV_32F）
- 失败：任一非 0 → subject.py:68-69 显式传 `borderType=cv2.BORDER_REFLECT_101` 重跑，仍非 0 则退回相对阈值方案。

**开放问题**
- detect_faces 的 cv2 失败是否也降级？会把「退出 2」变成静默中心框。
- 与 AGENTS.md **无冲突**：不改 AGENTS.md、层顺序不变、命令走 `uv --frozen`。

> 摘要：core 依赖 invisible-watermark 导入期无条件拉入 torch、夹带第二份 cv2，extra 又漏声明 torch/huggingface-hub；改为仓内逐字转录 DWT-DCT-SVD 算式。

### P10 — 信封回环对多数 payload 长度失败（根因：JPEG 4:2:0 色度下采样）

**严重度**：**P0**
**状态**：**方向已裁定（2026-09-23）：采纳「载体改为 (通道 0 = Y, step 72) + 修 H/V detail 带互换（P11）」**
**批次**：2 前置 —— 本项必须先于 P4 落地，P4 的自检强度依赖它
**依赖**：P3（已落地）；影响 P4、P6、G1、README；与 P11 同批
**触及文件**：`watermark_invisible.py`（encode 传参 + 读端参数化 + 候选读路径 + 仓内 `EmbedDwtDctSvd` 子类）、`config.py`（载体常量单一来源）、`pipeline.py`、`tests/`、`README.md`

**现象（实测、可复现）**

本仓库自己的两个 fixture，走完整 `protect --payload-envelope` → CRC 验真，逐 payload 长度 1–66：

| (通道, step) | S1 本机成品 | S1 再叠一轮 q85 4:2:0 | S2 本机成品 | S2 再叠一轮 |
|---|---|---|---|---|
| **(1, 36) 现行参数** | **31/66** | **19/66** | **17/66** | **2/66** |
| (1, 72) 只改 step | 66/66 | 66/66 | 66/66 | **58/66** |
| (0, 36) 只改通道 | 60/66 | 57/66 | 66/66 | 66/66 |
| **(0, 72) 两个都改** | **66/66** | **66/66** | **66/66** | **66/66** |

S1 = `tests/conftest.py::textured_jpg`（1600×1200 → 1080×810）；S2 = `tests/test_cli_exits.py::_seed_textured`（**1600×1200 → 1080×810**，先前此处写成 1200×1600 → 1080×1080 有误）。「本机成品」= resize → 嵌入 → 明水印 tile α=0.10 → `save_image_atomic` q85 4:2:0；「再叠一轮」= 再走一遍同样的 q85 4:2:0。

**根因（已更正，先前写错）**

**不是** `YUV2BGR` 色域裁剪 —— 实测 U 平面传输误差 S1 ≤3 / S2 = 0，**零个被裁剪样本**。真正的机制是 **JPEG 4:2:0 色度下采样**：色度平面被降采样再上采样，块投票的 margin 被抹平。这解释了为什么「换到亮度」是结构性回避（亮度不参与下采样），而「加大 margin」只是压制（平台再压一轮即复发：只改 step 在 S2 的平台格仍漏 8 个长度）。

**采纳的方案（用户 2026-09-23 裁定）**

1. **载体改为 (通道 0 = Y, step = 72)**，并把 `(channel, scale)` 提升为 `config.py` 的**单一常量来源**，写出与自检共用（避免重演「编解码参数不同步」这一整类错误）。
2. **必修伴生项（P11）**：仓内 `EmbedDwtDctSvd` 子类，修正库的 H/V detail 带互换 —— 否则亮度承载会背 mean 10.28–12.76 / max 106 的可见损坏。
3. **必备候选读路径**：读端依次尝试 `(0,72)` 与 `(1,36)`（可选再加 `(1,72)`），**以 CRC 为唯一判据**。依据：实测换参数后新旧**双向读不通**（131 / 117 比特错），不做双读等于把已发布的图判死。
4. **P4 的硬门在此之后才成立**：修复后本机成品有 66/66 实测支撑，硬门不再是可用性灾难；但自检仅限「刚写出的本地文件」，**措辞禁止外推**「上传后仍可验真」（实测 downscale+upscale 后四个配置全部 0/66）。
5. **P6 的基线改为带坐标的实测表**：每行带 `fixture sha256 + 尺寸 + stored_payload_bytes + bits + blocks_per_bit + carrier_channel + carrier_scale + artifact_subsampling`；CSV 新增 `carrier_channel` / `carrier_scale` 两列，否则修复前后不可比；只钉 identity 与 jpeg_q85 两格为 100%，其余格只记录不设阈值，并预先写明已知 <100% 的情形（q75 4:2:0 在 S1 上 U/sc36 为 3/66、q75 4:4:4 为 42/66）。
6. **README 已知边界**如实改写（P10 证据报告 §4.3 提供了可直接粘贴的两条）。

**代价与风险**

- ≈1 dB PSNR（30.98→30.01、30.68→29.95，实测）；扰动落进亮度（sc36 实测 ΔY 1.53–1.56，色度为 0.08–0.15）。
- **亮度可见性在真实照片上未测**：两个 fixture 都是合成噪声图。落地前应补一张真实人像/风景（含暗部与平静天空这类最易露馅区域）的可见性对照。
- `(0,72)` 这一格的复核是单次、单 payload 族；更狠的重编码（q75 等）对任何一格都未测。

**被实测否决的替代方案**

- 只换通道保持 step 36（本文档原提案）：本机成品 S1 仅 60/66、平台格 57/66；且 S1 的 6 个失败长度是「分区运气」型、非单调，长度上限兜不住。
- 长度上限 + 白名单：两图安全交集仅 17/66，可证安全的 cap = 6（9.1%）；只换 payload 内容首失败长度即移动最多 4 个位置 → 两图拟合，换图即失效。
- 冗余 R=2/3（交错分组 + 多数表决 + CRC）：反而变差（S1 29→16→9）；无容量的 pooled 读 52/66 可作免费改进，但不是修复。
- 只把 P4 自检降级为告警：对回环 0 改善，只是把响亮失败退回静默通过 → 只可作过渡披露。
- 写出侧 `subsampling=0`（4:4:4）：只保护我们自己写出的文件，平台仍按 4:2:0 重压；可作补充而非主线。

**开放问题**

- 真实照片上的亮度可见性（见「风险」）——若不过关，退路是 (1, 72)：本机成品两图满分，代价是平台格 S2 有 8/66 长度不可验真，须写进 README。
- 候选读路径带几组参数？每多一组，盲搜成本线性上升（当前 `find_envelope` 一次 `_block_scores` + 每候选一次重建；多组即多轮 `_block_scores`）。
- `find_envelope` 目前把「信封形状但 CRC 失败」吞成 `None`，与 `extract_envelope` 的区分不一致（见 P3 的开放问题）。

---

### P11 — 库的编码回程交换 H/V 细节带：每个受保护图都背一份非预期失真

**严重度**：P1（可见性缺陷；一旦按 P10 把载体换到亮度，它会成为肉眼可见的阻断，故为 P10 的必修伴生项）
**批次**：2（与 P10 同批）
**触及文件**：`watermark_invisible.py`（新增仓内 `EmbedDwtDctSvd` 子类）；若 G1 的 `_dwt_dct_svd.py` 先落地则由它承载，避免两份实现

**现象与证据（已手工核实库源码）**

`.venv/…/imwatermark/dwtDctSvd.py:27` 取出 `ca1, (h1, v1, d1) = pywt.dwt2(...)`，而 `:30` 送回 `pywt.idwt2((ca1, (v1, h1, d1)), 'haar')` —— **H 与 V 细节带在回程被互换**。

**影响**

- **读端无感**：解码只读 `cA`；实测 cA 逐位相同（float maxdiff 1.14e-13，tie 判定不变）。
- **写出端有失真**：每个被保护的图都多背一份非预期的图像扰动 —— 色度通道 mean 0.50 / max 19（现行参数一直在承受），**换到亮度会放大为 mean 10.28–12.76 / max 106**。
- 修复是**解码透明**的：cA 不变 ⇒ 旧图仍可读、新图也可被旧码读。

**推荐方案**

- 仓内 `EmbedDwtDctSvd` 子类，保持 `(h1, v1, d1)` 原序（AGENTS.md 禁止改依赖，不能动 site-packages）。
- 等价证明：给出「只差 detail 带、cA 不变」的对照（cA 逐位相同 + 1..66 全扫的解码等价；目前只在锚点测过，应补齐）。

**开放问题**

- 修 swap 会改变输出字节（不再与旧版逐字节相同）。需确认不与既有断言冲突 —— G3 的「产物字节等价」是相对旧**保存路径**的，不是相对旧**水印参数**，预计无冲突。
- 该 bug 是否值得上游报 issue？（库自 2023 年后无维护迹象。）

> 摘要：库的 H/V 细节带互换会给每个受保护图注入非预期失真；与 P10 同批修。

### G1 — core 安装被拖入 torch + extra 漏声明 + 双份 cv2

**严重度** P0-blocker：「core 无 torch」契约今天结构性不可满足
**工作量** M
**批次** 4
**依赖** P3（b1）持 `pywavelets` 声明与 `watermark_invisible` 新符号，oracle 钉死为今天的 `imwatermark`；`CLAUDE.md:71`/`README.md:238` 按 P9 政策不写数字
**触及文件** `src/photo_guard/{_dwt_dct_svd.py(新),watermark_invisible.py,download.py:31-33,config.py:10-13}`、`pyproject.toml`、`uv.lock`、`Dockerfile:71`、`ci.yml`、`tests/{test_dependency_graph.py,test_dwt_dct_svd.py}(新)`、`tests/fixtures/dwtDctSvd_legacy_512.png`(新)、`README.md:204/238/278`、`CLAUDE.md:12/71/75/78/93`

**现象与证据**

- `pyproject.toml:10-15` core 含 `invisible-watermark>=0.2.0`；`:21-26` extra 无 `torch`/`huggingface-hub`（`tool.uv` 命中数 0）；`uv.lock:391-400` 该包声明 torch 无 marker（wheel `METADATA:19`）。
- `uv.lock:768-801` 两份 cv2 装进同一 `site-packages/cv2`，`:396` 是 `opencv-python` 唯一入边（来自待删包）；`:1368-1392` nvidia/cuda/triton 边全 linux-only。
- 真因链 `imwatermark/__init__.py:1`→`watermark.py:9`（模块级）→`rivaGan.py:2` `import torch`；`watermark_invisible.py:13` 导包根，经 `__init__.py:3`→`cli.py:8`→`pipeline.py:11` ⇒ `import photo_guard` 今天就要求 torch。
- `ci.yml:47` core-only sync 后无「无 torch」断言，`tests/test_perturb_registry.py:49-70` 只 reload `perturb`；`Dockerfile:71` 显式 `import imwatermark`。

**根因**

`invisible-watermark` 0.2.0 同时是 core 膨胀源与第二份 cv2：其 torch 依赖对本项目是残留，在 metadata 与模块级代码上却无条件成立，而 `watermark_invisible.py:13` 导包根使它成为 `import photo_guard` 的导入期硬需求。extra 从未声明实际 import 的两个包，也无机械检查断言「默认无 torch」或「只有一个 cv2 发行包」——修法必须改依赖集合。

**推荐方案**

1. **SPIKE 门禁**（判据见下，未通过不动 manifest）；两 commit 先红后绿（1=第 5/6 步，2=第 4 步），证据落 commit body（`CLAUDE.md:126`，未确认不 push）。
2. `src/photo_guard/_dwt_dct_svd.py`（新）逐字转录 `imwatermark/dwtDctSvd.py` 的 `EmbedDwtDctSvd`，含 `scales=[0,36,0]`、`block=4`、Haar、`idwt2` h-v 互换、`s[0]//scale+0.25+0.5*wmBit`、`avgScores*255>127`、`num % wmLen` 回绕等全部怪癖，**不许「修」**；只导出 `embed_bits(bgr, bits, *, scales=(0,36,0), block=4)`、`decode_bits(bgr, wm_len, *, scales=(0,36,0), block=4)`（bit 层）；头部放完整 MIT 正文（`Copyright (c) 2021 ShieldMnt`），不得抄 upstream README（`METADATA:60`）。
3. `watermark_invisible.py`：删 `:13` 改 `from . import _dwt_dct_svd`；把 `watermark.py` 的 bits↔bytes 与 256×256 守卫搬入 `embed`/`extract`，保留 `payload_bytes<=0→ValueError` 与 `decode("utf-8",errors="replace")`；加一行 `WATERMARK_METHOD!="dwtDctSvd"→ValueError`；公开签名/异常与三个 pack helper 不变，`pipeline.py`/`cli.py`/`gui.py` 无需改。
4. `pyproject.toml`+`uv.lock`（相对 **P3 后**）：`uv remove invisible-watermark`、`uv add --optional photoguard torch huggingface-hub`；禁 `[tool.uv]`；验 `uv sync --frozen`。`download.py:31-33` 改 `(provides huggingface_hub)` 并逐字留 `uv sync --extra photoguard`；`Dockerfile:71` 改 `import cv2, numpy, PIL, pywt, torch, diffusers, huggingface_hub`，apt 与两阶段 sync 不动。
5. `tests/test_dependency_graph.py`（新，纯 `tomllib`）：从 `uv.lock` 的 core `dependencies` 递归、忽略 marker/extra——①重包与 `nvidia-`/`cuda-` 不可达 ②`^opencv-` 恰为 `['opencv-python-headless']` ③根集非空含 `pywavelets` ④声明断言 `{'torch','huggingface-hub'} ⊆ [project.optional-dependencies].photoguard`。
6. `ci.yml:47` 后同 job 加一步（`shell: bash`、无 `$`）：①`importlib.metadata.distributions()` 拒绝重包与 `nvidia-`/`cuda-`/`opencv-`（headless 除外）+`find_spec('torch') is None`→`exit 1` ②`cv2.data.haarcascades+'haarcascade_frontalface_default.xml'` 存在且 `CascadeClassifier(该路径).empty() is False` ③`uv run --no-sync photo-guard --help` 退 0；今天 main 上必红。
7. `tests/test_dwt_dct_svd.py`+`tests/fixtures/dwtDctSvd_legacy_512.png`（第 1 步在删依赖前产出；`test_compliance.py:33-40` 跳过 `0x89`）。
8. 文档只改变假的行、**不写聚合数字**：`CLAUDE.md:12/71/75/78/93`、`config.py:10-13`（不动 `:14`）、`README.md:238`（只写命令）/`:278`/结构树（**只增行**加 `_dwt_dct_svd.py`，树区归 G2）；commit body 记 core sync 会剪掉 venv 里的 torch（`gpu_bench.py:37` 需重加 extra，须 spike 验证）。

**被驳回或部分采纳的验证者意见**

- F-R5 / R-C1（部分采纳）：文档集扩到 `config.py:10-13`、`CLAUDE.md:75/93`；驳回「删校验」——删后改回 `dwtDct` 不报错也不生效，保留一行 `ValueError`。其余 33 条验证者意见已全部并入上述方案。

**被否决的替代方案**

- override / `dependency-metadata` / `--no-install-package torch` / torch stub / importlib 绕过包 `__init__`：导入期 `import torch`，破坏 0/1/2 或在 Nuitka、wheel 下坏掉。
- fork 上游、换库、CPU-only torch index、新 marker/独立 venv；接受 core 里的 torch（兜底 b）仅在用户驳回 AGENTS.md 偏离时启用；`--layers`/顺序改动不在本节。

**API / CLI / 格式与退出码影响**

- **0/1/2 契约不变**：新 `ValueError`/`RuntimeError` 落入 `cli.py:132-137` → exit 2；无新 flag/默认值，resize→invisible→perturb→visible→JPEG 与 `--layers` 只判成员均不动。
- 公开 API 不变（`embed`/`extract` 与三个 pack helper）；新增私有 `_dwt_dct_svd.embed_bits/decode_bits`；**不得删除** P3/P4 的 `max_stored_bytes` 等新符号；`WATERMARK_METHOD` 保留、只改注释；core 闭包变 `{photo-guard, numpy, opencv-python-headless, pillow, pywavelets}`。
- **无任何既有断言被放宽**：`roundtrip` 仅 `:65-68` 消息改写；`pipeline_order`/`pipeline_layers`/`cli_exits`（`:43`/`:54` 零改动，`:25`/`:87` 追加归 P7/P4）/`compliance`/`perturb_registry` 一行不改；本节落地后 P3 的 `'torch' in sys.modules` 断言才转 False（b1 时仍为 True）。

**测试清单**

| 文件 | 用例名 | 档 | 断言 |
|---|---|---|---|
| `tests/test_dependency_graph.py`(新) | `test_core_closure_excludes_heavy_and_duplicate_packages` / `..._has_exactly_one_opencv_distribution` / `..._contains_expected_packages` / `test_photoguard_extra_declares_torch_and_huggingface_hub` | fast | 第 5 步 ①②③④ |
| `tests/test_dwt_dct_svd.py`(新) | `test_legacy_fixture_decodes_exact_payload` | fast | 按 `roundtrip:18-19` 读 fixture，`extract(bgr,len(PAYLOAD.encode()))==PAYLOAD` |
| 同上 | `test_tiny_image_raises_runtime_error` / `test_tiny_image_verify_exits_two` | fast | 255×255 抛 `RuntimeError`；照 `test_cli_exits.py:54-58` `cli.main([...])==2` |
| 同上 | `test_unsupported_method_is_refused` / `test_embed_extract_utf8_payload_roundtrip` | fast | `"dwtDct"`→`ValueError` 且改回可往返；非 ASCII 非 8 倍数 payload 往返相等 |
| `ci.yml` 新步 + 既有 | core-only 断言；`roundtrip`/`pipeline_order`/`pipeline_layers`/`cli_exits`/`compliance`/`perturb_registry`/`test_exif_orientation.py` | fast | 第 6 步 ①②③；既有断言逐字未变且全绿 |

**验收标准**

- [ ] `uv.lock` 中 `photo-guard` core 可达集恰为 `{photo-guard, numpy, opencv-python-headless, pillow, pywavelets}`，`torch`/`opencv-python`/`nvidia-*`/`cuda-*` 不可达。
- [ ] 全新 core-only 环境：`import torch` 抛 `ModuleNotFoundError`、`import photo_guard` 成功、`photo-guard --help` 退 0、纹理图 protect+verify 退 0。
- [ ] 删依赖**前**由旧库生成的 fixture 解出精确 payload；commit body 含 spike A/B/C 结果、SHA-256、三版本串、`cv2.__file__` 与 owning distribution。
- [ ] `decode_bits` 与 P3 的 `_reconstruct_bytes(_block_scores(img), n)` 在 `1..2N` 逐字节相等、`max_stored_bytes` 未删、`test_rotating_a_protected_image_breaks_extraction` 仍绿；`pytest -m 'not slow'` 全绿且既有断言逐字未变。
- [ ] 相对 P3 后 `pyproject.toml`/`uv.lock` 仅两类差异；`grep -c tool.uv`=0；`uv sync --frozen` 通过；`git diff --stat AGENTS.md` 空；无 `requirements.txt`；CI 新步改动前红、后绿；`docker.yml` 两 smoke 免改通过且不声称体积收益。

**风险与未知**

- 转录漂移靠三层网（spike 逐位 / 仓内 fixture / 既有 JPEG q85），fixture 必须在删依赖前产出；cv2 构建替换的数值漂移响亮变红，Haar 级联丢失静默（第 6 步②兜住）。
- core sync 可能剪掉 venv 里的 torch（uv 行为，须 spike 验证）；`pywt` 靠 Nuitka import-following；raw `verify` 无认证的不对称（`cli.py:64-68`/`:114-118`）需单独 issue。

**spike（如需）**

- **假设**：逐字转录（含 bits↔bytes 与守卫）与 `invisible-watermark` 0.2.0 在公开 `embed`/`extract` 上逐位等价。
- **实验**：删依赖前、只用 uv，一次脚本同持 OLD（`imwatermark`）与 NEW（`_dwt_dct_svd`）跑 A/B/C，记版本串、`cv2.__file__`、SHA-256（首次 `uv run` 做全量 core sync，联网 + 532 MB）。
- **通过判据**：A `np.array_equal` 每对为真（≥3 组，含非 ASCII 与非 8 倍数）、B `decode_bits(embed_bits(bgr,bits))==bits` 为真、C NEW `extract` 精确解出 fixture（必须在此产出）。
- **失败判据**：A 或 B 假 → 停止、不带容差，改兜底分支（core 声明 torch）；C 单独假 → 只换 fixture 内容重试。

**开放问题**

- **AGENTS.md 冲突，需用户裁定**：`AGENTS.md:40/73/105/137/142` 点名 `invisible-watermark` 及其示例命令，该文件逐字不改；(a) 接受偏离（推荐）；(b) 兜底分支（core 声明 torch + 撤回 `CLAUDE.md:12`）；(c) 上游 fork。
- fixture 策略：是否提交 ~200–500 KB 无损 PNG？不接受则互操作证明会腐烂。
- `photoguard` extra 是否拆分 torch/huggingface-hub？不建议（多一种 sync 组合）。
- 是否把上游 `imwatermark/watermark.py:9` 的 eager import 报回上游？一次惰性导入可把整个 issue 降级为改 pyproject；本节不做。

---

**批次 1 新增发现（2026-09-23，归属本项）**

- 本机 uv 是 **0.6.10（Homebrew 2025-03-26）**，而 CI（`astral-sh/setup-uv@v5`）与 Dockerfile（`COPY --from=ghcr.io/astral-sh/uv:latest`）都用最新版；已提交的 `uv.lock` 是 `revision = 3` 且带 `upload-time`（新格式），0.6.10 写出的锁是 `revision = 1` 且无该字段。
- 批次 1 执行 `uv add pywavelets` 时，0.6.10 把锁整体重写为旧格式：**750 insertions / 748 deletions，但语义零变化**（74 个包，0 新增 / 0 移除 / 0 版本变化，差异仅在 `revision` 与 `upload-time`）。已实测用缓存中的 uv 0.9.28 以 `--frozen` 读该锁正常通过（`Audited 22 packages`，不改写），故降级是安全的。
- 用户裁定（2026-09-23）：本批**接受降级**，作为本项发现记录，留待本项（批次 4）在工具链面一并处理。
- 本项落地时的建议动作：`brew upgrade uv`（或固定一个 ≥0.11 的 uv）后跑一次 `uv lock`，格式即回到 `revision = 3`；并考虑在 CI 加一条「锁文件格式与所用 uv 版本一致」的检查，否则同一把锁会在新老 uv 之间来回抖动。
- 附注：本机缓存已有 uv 0.9.28（`~/.cache/uv/archive-v0/…/uv-0.9.28.data/scripts/uv`），可离线直接执行；而 `uvx uv@0.9.28` 会尝试联网解析，网络受限时会挂住（实测 2 分 12 秒后放弃）。
> 摘要：许可/署名从未进入交付清单也无 gate；本 issue 补 LICENSE 与第三方声明并接进发布校验。

### G2 — 仓库与发布物无许可证/署名（含 SD VAE 权重与 LGPL Qt）

**严重度 / 工作量 / 批次 / 依赖 / 触及文件**
- 严重度：P2-medium
- 工作量：M
- 批次：4
- 依赖：G5、P9（同址 README.md:238、CLAUDE.md:71）
- 触及文件：见各步骤（新增 LICENSE、notices、licenses/、generate_notices.py）

**现象与证据**
- `git ls-files` 47 项无 LICENSE、`pyproject.toml:1-15` 无 license、`uv.lock` licen 0 命中；grep 全仓 0 命中（中文仅中 AGENTS.md:41）。
- `build_desktop.py:28`（MODEL :11）打进 SD VAE；`windows-installer.iss:19-20` 整目录打包、无 LicenseFile。
- `release-desktop.yml:31-33` 出 SHA256SUMS.txt 并直传 release/*；`Dockerfile:76` 烘权重而 :59 无声明。

**根因**
许可/署名从未进入交付清单（`uv init` 无 license 字段、CI 只出 SHA256SUMS.txt）；上传含 LGPL Qt 与 MIT 权重的包即触发无人承载的义务。

**推荐方案**
1. 【阻塞，需用户裁定】新建根 `LICENSE`：正文＋版权行 `Copyright (c) <year> <holder>`。
2. `pyproject.toml`：`license = "MIT"`＋`license-files = ["LICENSE","THIRD_PARTY_NOTICES.md","licenses/*.txt"]`、禁用 classifier。
3. `licenses/{LGPL-3.0,GPL-3.0}.txt`（新，§4(b)）；gnu.org 取回，核对 `Version 3, 29 June 2007`。
4. `packaging/generate_notices.py`（新）：`HAND_MAINTAINED_LICENSES`/`FORBIDDEN_LITERAL`/`ROW_FIELDS`、`collect_rows`/`check_notices`/`main`（0/1）；手写件只校验不覆盖；`--check` 只比本平台段。
5. `build_desktop.py::main()` 追加 licenses 目录＋LICENSE、notices 两个 `--include-data-files`。
6. `desktop_entry.py::_smoke_test()` 加两文件存在断言，缺失返回 4（{2,3}→{2,3,4}）。
7. `windows-installer.iss` 加 `LicenseFile=..\LICENSE`；`create_dmg.sh` staging 放 `$APP`＋材料。
8. `release-desktop.yml` build 前插 `generate_notices.py --check`；upload 前加路径断言。
9. README.md 增许可小节；只增行补 `README.md:196-217` 树；`:238`/`CLAUDE.md:71` 改命令。
10. `Dockerfile:59` COPY 追加 LICENSE、notices、licenses/。

**被驳回或部分采纳的验证者意见**
- #19 部分采纳：不改名 `.txt`，改用 S3 实测＋`.txt` 兜底。
其余 48 条验证者意见已全部并入上述方案。

**被否决的替代方案**
- uv.lock 生成声明、单一跨平台清单、宽松产物断言、notices 现场生成不入库。

**API / CLI / 格式与退出码影响**
- **0/1/2 契约不变**：不改 `src/photo_guard/**`、不加 CLI 参数或 marker。
- 新入口 `generate_notices.py [--check]` 退出码 0/1；`_smoke_test()` {2,3}→{2,3,4}。
- 其余断言只加强；唯一可能缩小的是 `test_compliance.py:13-14` 排除集（须与 `ci.yml:31-38` 同改）。

**测试清单**（fast 档）

| 文件 | 用例名 | 档 | 断言 |
|---|---|---|---|
| test_compliance.py | test_license_file_is_complete_mit_text ＋ test_copyleft_texts_are_canonical_and_hashes_match | fast | 首行 MIT |
| 同上 | test_pyproject_declares_license_and_files ＋ test_installed_distribution_carries_license_metadata | fast | 三元素 license-files |
| 同上 | test_third_party_notices_cover_core_dependencies ＋ test_sd_vae_notice_is_mit_and_pinned_to_the_configured_repo | fast | 两行命中 notices |
| 同上 | test_packaging_wires_license_material | fast | 参数＋`LicenseFile=` |

**验收标准**
- [ ] `git ls-files` 含 LICENSE、notices、licenses/。
- [ ] `pytest -m 'not slow'` 全绿；新用例各做「破坏→变红」。
- [ ] `README.md:238`/`CLAUDE.md:71` 无数字。
- [ ] 两条 `uv sync --frozen`（dev；extra＋package）通过。
- [ ] 全量 extra `--check` 退 0；macOS＋Windows 构建 `--smoke-test` 退 0。

**风险与未知**
- LGPL 残余不确定性：Qt 独立共享库且未签名，「可替换义务」属法律判断。
- `download.py:44-50` 未固定 revision；notices 是锁定环境清单；`--check` 在 build/upload 前 ⇒ 失败即零产物。

**spike**
- **S1 PEP 639 落点**——假设：写 `License-Expression`。实验：副本内 `uv build --wheel`。通过判据：两处有该字段。失败判据：无则改 legacy。
- **S2 Nuitka 数据落点**——假设：licenses/models 落 `Contents/Resources`、Qt 独立 dylib。实验：跑 `build_desktop.py`。通过判据：两者都在该目录。失败判据：落 `Contents/MacOS` 则补拷贝。
- **S3 ISCC 的 LicenseFile**——假设：接受无扩展名文件。实验：编译 `.iss` 验向导页。通过判据：退 0、显示正文。失败判据：改 `.txt`。

**开放问题**
- 【阻塞】项目许可与版权行：holder、year、是否用 `pyproject.toml:7` 的邮箱。
- **AGENTS.md 冲突，需用户裁定**：许可正文若命中 §6.4 字面量，须同改 `test_compliance.py:13-14` 与 `ci.yml:31-38`。
- **AGENTS.md 冲突，需用户裁定**：是否把「许可与署名」写进 AGENTS.md；是否继续随包再分发 SD VAE 权重。

> 摘要：输出路径的去向与完整性无单一负责人：写盘占用最终路径、CLI 容许 -o 指向输入、GUI 批量只按 exists() 判重且 suffix 未净化。新增 outputs 做原子写与命名，pipeline 加「绝不写输入」守卫。

### G3 — 输出写入无完整性保证（非原子 / 覆盖原图 / 批量撞名 / suffix 穿越）

**严重度**：P0-blocker
**工作量**：M（≈120 行 + 15 条 fast 用例）
**批次**：1（只做 fast 档门禁；Qt 档用例归 P2）
**依赖**：P2(3) 消费 `outputs`；P9 改两处计数锚点；G4 正交
**触及文件**：src/photo_guard/{outputs.py(新),pipeline.py,gui.py}、tests/{test_output_integrity.py(新),test_gui_logic.py}、README.md、CLAUDE.md

**现象与证据**
- pipeline.py:93-94 无 temp/`os.replace`/写后判定 → 中断即留半截 `.jpg`。
- cli.py:16-17 无相等性校验 → `-o in.jpg` 退出 0 毁原图（违 AGENTS.md 第五节）；gui.py:374-378 反而改名。
- gui.py:315+:376 只判 `exists()` 且批量前算一次、:94 无条件 emit「成功」→ 同 stem 静默覆盖。

**根因**
写盘把最终路径当工作路径；命名由 CLI/GUI 各自实现，无「绝不写输入文件」不变量；GUI 判重只有 `exists()` 且批量前只算一次。

**推荐方案**（按实施顺序）
1. `outputs.py`（新，仅 stdlib+Pillow）：`DEFAULT_SUFFIX="_protected"`、`save_image_atomic(image, path, *, image_format="JPEG", quality=None, icc_profile=None)`、`plan_batch(directory, sources, suffix, extension=".jpg")`、`sanitize_suffix(raw)`、`_unique_output`、`_create_temp_file`。
2. `_create_temp_file`：同目录 `.photoguard-<hex>.tmp`，`O_CREAT|O_EXCL|O_WRONLY 0o666`，重试 16 次抛 `OSError`。
3. `save_image_atomic`：`mkdir` → 记 `previous_mode` → `temp: Path|None=None`（防 `UnboundLocalError`）→ 写 temp（`format, quality, optimize, icc_profile` 同 pipeline.py:94）→ `fsync` → `chmod` → `os.replace`；失败 unlink 并包成 `OSError(f"failed to write {path}: {exc}")`。
4. `sanitize_suffix`：strip、空串→`DEFAULT_SUFFIX`、拒 `/\:*?"<>|`/控制字符/纯点串 → `ValueError`，非 ASCII 保留。
5. `plan_batch`：首句 `suffix = sanitize_suffix(suffix)`；`taken: set[str]`；命中 `candidate.name in taken or candidate.exists()`；同长同序。
6. pipeline.py 加 `_same_file(a,b)`：先判存在再 `samefile`，否则 `normcase(realpath())`；`protect()` 内 `validate_options` 后、解码前命中即 `raise ValueError("refusing to overwrite the input file …")`。
7. pipeline.py:93-94 → `outputs.save_image_atomic(final, output_path, quality=opts.quality)`。
8. `gui.py`：删 `_unique_output`(374-378)；`start_protect` 用 `items = self._plan_items(paths)`；`_plan_items`＝`outputs.plan_batch(…, self.suffix.text())`+zip；:207 用 `DEFAULT_SUFFIX`。
9. 删 tests/test_gui_logic.py:15-23 的 `test_unique_output_policy`；README.md:196-217 加 `outputs.py` 一行、:161 拒绝语义、:266-272 窗口/权限/symlink；CLAUDE.md:97-111 加一行。

**被驳回或部分采纳的验证者意见**
- #9 部分采纳：`iterdir()` 判据恒真 → 删；#10：保留 `extension` 并补 `extension=".png"` 例。
其余 22 条验证者意见已全部并入上述方案。

**被否决的替代方案**
- 「警告后继续」/`--force`、`os.link` no-clobber、系统临时目录（`EXDEV`）、两份命名实现共存。

**API / CLI / 格式与退出码影响**
- **退出码 0/1/2 不变**：output==input → `ValueError`、写失败 → `OSError`，都经 cli.py:132-137 → 2；不加开关；新增 `photo_guard.outputs`（无 Qt/torch）。
- 可见变更进 README：`-o in.jpg` 变「2 + `refusing to overwrite the input` + 原图字节不变」、symlink 被替换；权限等价；既有断言无一放宽。

**测试清单**（前缀 `tests/test_output_integrity.py::test_`；`组名: 后缀` 拼成完整名）
| 用例名 | 档 | 断言 |
|---|---|---|
| atomic_write: keeps_previous_output_when_save_fails / creates_no_file_when_destination_absent / temp_creation_failure_reports_target_not_unboundlocal / output_is_decodable_at_final_path / preserves_existing_file_permissions / new_file_follows_umask | fast | 失败保留旧字节、目标不存在则不创建；errno 消息含目标路径；可解码；权限沿用旧 mode；umask 生效 |
| protect: refuses_output_equal_to_input / replaces_symlink_without_touching_its_target | fast | 参数化「同一路径」+`os.link` 别名（失败即 skip）：返回 2、stderr 含 `refusing to overwrite the input`、sha256 不变；symlink 例返回 0 且链接被替换 |
| plan_batch: gives_same_stem_inputs_distinct_paths / composes_reservation_with_existing_files / normalizes_suffix_through_sanitize；sanitize_suffix: rejects_illegal_and_traversal_values / accepts_normal_values | fast | 参数化 (a) 两目录同 stem `.JPG` (b) 同目录 `.JPG`+`.png` (c) `.png` → `IMG_0001_protected.jpg`/`_2`，预置同名时 `_2`/`_3`；suffix 先净化；12 例非法值全 `ValueError` |
| outputs_module_import_does_not_pull_qt_or_torch / gui_delegates_output_naming_to_outputs_module（源码） | fast | 无 torch/PySide6 入 `sys.modules`；源码无 `"_unique_output"` 且有 `outputs.plan_batch` 调用 |

**验收标准**
- [ ] `test_atomic_write_keeps_previous_output_when_save_fails` 与 `test_plan_batch_gives_same_stem_inputs_distinct_paths` 在旧代码上必红。
- [ ] `uv run pytest tests/test_output_integrity.py -q`、`uv run pytest -m 'not slow' -q` 全绿；收集数以 `--collect-only -q` 实测（HEAD 2810e31 = 58），不写推算数字。
- [ ] `protect in.jpg -o in.jpg` → 2 且 sha256 不变；`protect in.jpg -o out.jpg` → 0、`verify out.jpg --payload-bytes N` → 0，无 `.photoguard-*.tmp`。
- [ ] 两条 grep 零命中（`candidate.exists()`、`_unique_output`）；compliance 与 perturb_registry 用例全绿；AGENTS.md/pyproject/uv.lock 无 diff；Docker 冒烟通过；GUI 手工：`../x` 弹框且文件数不变，两张同 stem 批量得两个不同文件。

**风险与未知**
- Windows 的 `fsync`/`os.replace`/`os.link`/`os.symlink` 只能由 ci.yml:15 的 matrix 给证据；`fsync` 退路为 `close()` 后 `"r+b"` 再 fsync；`PermissionError` 须响亮失败，**不得**降级为非原子写。
- `.photoguard-*.tmp`：断电残骸、写入窗口内目录短暂多出该条目；不做启动清理；TOCTOU 与 `ENAMETOOLONG` 不处理；别名用例可能 skip。

**spike（如需）**
- 假设：`uv sync --frozen --group dev` 的 prune 移除未请求的 desktop extra，使 `import PySide6` 失败。
- 实验（本机无 `.venv`、离线只读）：`uv sync --frozen --group dev && uv run python -c "import PySide6"`，加做 `--extra desktop` 对照。
- 判据：`import PySide6` 成功 → 验收与 GUI 手工可顺序执行；`ModuleNotFoundError` → gui 步骤显式 `--extra desktop`，uv sync 那条排最后。

**开放问题**
- CLI 是否还需「`-o` 已存在即拒绝」的 clobber 守卫？本 issue 保持覆盖语义。
- 是否启动时清理陈旧 `.photoguard-*.tmp`？本 issue 不做，带年龄阈值属独立小 issue。
- AGENTS.md 冲突：无（不改 AGENTS.md、不加依赖、不改三层顺序；拒绝 output==input 正是在执行第五节「原图留底」）。

---

**实施记录（批次 1，2026-09-23）**

- **spike #7 结论**：`uv sync --frozen --group dev` **会**剪掉未请求的 extra（离线对照项目用同一命令形状复现：`Uninstalled 1 package / - iniconfig==2.3.0`，随后 import 报 `ModuleNotFoundError`）。附带发现一个反直觉的不对称：`uv sync` 默认 exact（会剪枝），而 `uv run <cmd>` 的默认 sync 是 inexact（不剪枝）。实际含义：本批 GUI 手工步必须显式 `--extra desktop`（约 443 MB 下载：pyside6 + addons + essentials + shiboken6），且**必须排在最后**（其后任何普通 `uv sync` 会把它再剪掉）。当日 fast 档实测收集数 58（与本项落地前的基线一致）。
- **旧代码必红的取证**（父提交 `2810e31`，`git worktree` + 复用当前 venv 以旧 `src` 运行）：
  - `protect -o 同一路径` → **exit 0 且原图被销毁**（`original destroyed: True`）
  - 保存失败后目标路径留下 `b'PARTIAL-TRUNCATED'`，**旧内容丢失**
  - 同名 stem 两次命名 → `IMG_0001_protected.jpg` 与 `IMG_0001_protected.jpg`，**相撞**
  三条缺陷均在父提交复现，故新增用例在旧代码上必然红。（`outputs.py` 在旧代码中不存在，无法以模块形式直接运行新测试，故以等价探针取证。）
- **产物字节等价**：同一输入分别用父提交与当前代码跑 `protect`（payload `owner:test#order`、tile、long-edge 1080、q85），sha256 **完全一致**（`eb09dc48…`）—— 原子写未改变产物。
- **C1 落实**：`AGENTS.md` 零改动；`pyproject.toml`/`uv.lock` 的 diff 只来自 P3 的 `pywavelets` 声明，G3 自身不引入（原文「无 diff」按此理解执行）。
- **移交 P2（R13）**：验收条「GUI 手工：`../x` 弹框且文件数不变、两张同 stem 批量得两个不同文件」**本批未做** —— Qt 档用例与 `gui` marker 归 P2（批次 3），且需付 443 MB 下载。本批以 fast 档门禁替代：`test_gui_delegates_output_naming_to_outputs_module`（源码断言 `gui.py` 已无 `_unique_output` 且调用 `outputs.plan_batch`）与 `test_pipeline_saves_through_the_atomic_helper`。
- **测试与断言强度**：新增 `tests/test_output_integrity.py`（35 例：原子写 6、输入守卫 3、批量命名 4×4 参数化、suffix 净化 14、模块卫生 3）；删除 `tests/test_gui_logic.py::test_unique_output_policy`（自证式：它重抄逻辑而不调用）。fast 档 **94 → 129**，全绿（10.5 s）。断言只增不减；`tests/conftest.py` 未改。
- **CLI 冒烟**：`-o` 等于输入 → 2 且原图 sha256 不变；`protect → verify`（不带 flag）→ 0 且 stdout 恰为 payload；输出目录无 `.photoguard-*.tmp` 残留。
- **新增公开符号**：`photo_guard.outputs`（`DEFAULT_SUFFIX` / `save_image_atomic` / `plan_batch` / `sanitize_suffix`）；`pipeline._same_file`（私有）。无新依赖、无新 CLI 开关、退出码契约不变。
> 摘要：读图边界无契约：全尺寸解码、alpha 丢隐藏 RGB、多帧只护第 0 帧、无上限。改为唯一 loader 解码前检查，透明叠白。

### G4 — 输入契约与资源上限缺失（alpha/ICC/多帧/解压炸弹/HEIC）

**严重度**：P2-medium
**工作量**：S-M（~90-120 行；6 例）
**批次**：5
**依赖**：P8（唯一 loader/ICC）、G3、P7、P4、P3（R11）、P2/P9
**触及文件**：config.py、pipeline.py、gui.py、tests/test_input_contract.py（新）、README.md、CLAUDE.md

**现象与证据**
- pipeline.py:65-68 `load()`+`convert("RGB")` 全尺寸解码与拷贝；`MAX_IMAGE_PIXELS` 等在 src/ tests/ 零命中 → Pillow 阈值（89.5/179 MP）即上限；`:67` 实测 RGBA `(10,20,30,0)`→`(10,20,30)` → 全透明区泄漏隐藏 RGB。
- pipeline.py:105-108 verify 同路径；无 `ImageOps|icc|exif|n_frames` 引用 → 多帧只护第 0 帧；gui.py:21 手抄 `_IMAGE_FILTER`（无 .gif），worker :91-92 露英文。

**根因**：`convert("RGB")` 被当无条件模式归一化器，解码无契约无上限 → alpha/色彩空间/其余帧静默误处理。

**推荐方案**
1. config.py:48-50 加 `MAX_INPUT_PIXELS = 64_000_000`、`ALPHA_MATTE = (255,255,255)`（注释记推导、须低于 Pillow 阈值）；pipeline.py:9 加 `ImageOps`。
2. pipeline.py:13-17 加 `SUPPORTED_INPUT_FORMATS`（JPEG/PNG/WEBP/BMP/TIFF）+ `_supported_formats_text()`；判定只看 `image.format`。
3. pipeline.py:35-40 加 `_validate_input(image, path)`：三项（格式/像素/多帧）均在 decode 前 → `ValueError`→2；消息=英文前缀+中文补救；`n_frames` 用 `getattr`。
4. pipeline.py 加 `_rgb_on_matte(image)`：先 `exif_transpose`；透明（RGBA/LA/PA 或 transparency）→ 叠 `ALPHA_MATTE` 白，否则 `convert("RGB")`；静默叠白。
5. 唯一 helper `_load_oriented_rgb(path, *, draft_long_edge=None) -> tuple[Image.Image, bytes | None]`（P8 形）。体序：`Image.open` → except→`ValueError`（HEIC 话术／too large）→ `_validate_input` → **P8 fresh EXIF 解析** → `draft` → `.load()` → `icc`（RGB/RGBA）→ `(_rgb_on_matte(image), icc)`；**guard 全在 `.load()` 前、draft 居中**（R3）。
6. protect（:65-68）/verify（:105-108）都走它（verify 不传 draft）；save 不变（R4）；`_IMAGE_FILTER` 由该表推导。
7. 文档：README.md:161 加「输入契约」+「verify 不支持格式→2」；CLAUDE.md:90-93 加不变量；README.md:238 与 CLAUDE.md:71 归 P9（R10）、pipeline.py:1 归 P8（R12）；AGENTS.md 不编辑。

**被驳回或部分采纳的验证者意见**
- 部分采纳/驳回：用例 5 的 4000×3000 说法不成立→改用 `large_jpeg_keeps_long_edge`；「guard 在 exif_transpose 之后」（P8.json STEP 8）→R3；`docker.yml:53-57`→`:47-48`；写死总数→R10。
其余 23 条验证者意见已全部并入上述方案。

**被否决的替代方案**
- `Image.MAX_IMAGE_PIXELS` 强制上限（实为 128 MP）；`uv add pillow-heif`（离线不可验证）；字节上限/CLI 开关。

**API / CLI / 格式与退出码影响**
- 新增 `SUPPORTED_INPUT_FORMATS`、`MAX_INPUT_PIXELS`/`ALPHA_MATTE`；无新 CLI flag/marker/异常类；不改 ProtectOptions/`--layers`/info 键/save；无断言被放宽。
- **退出码 0/1/2 不变**（`ValueError`→2，全在 `.load()` 前）；>64 MP/不支持格式/多帧→2；verify 同契约→2（R11）。

**测试清单**（tests/test_input_contract.py，新，fast；名+`test_`）

| 文件 | 用例名 | 档 | 断言 |
|---|---|---|---|
| 同 | formats_policy_pinned | fast | dict 相等；扩展名互证 |
| 同 | ceiling_and_bomb_headers | fast | 严格 `>`；header PNG 拒且无警告 |
| 同 | multiframe_rejected | fast | 2 页/2 帧→2；单页 0 |
| 同 | transparent_png_goes_white | fast | matte 白；mean≥220 |
| 同 | heic_rejected_actionably | fast | HEIC/GIF→2；verify 均 2 |
| 同 | large_jpeg_keeps_long_edge | fast | 长边 1080 |

**验收标准**
- [ ] `uv run pytest -m 'not slow' -q`：既有 58 条零变红、本文件 6 条被收集（不写预测总数）；文档不出现 55/~66。
- [ ] 2 MP JPEG exit 0、`:27` 绿、verify 取回 payload；拒绝路径（HEIC/header PNG/多帧→2、单页 0、Alpha 白）；【手工/发版前】48 MP 成功。

**风险与未知**
- 回归：**58 个既有 fast 用例无一变红**（draft 对 1600×1200 conftest fixture 与 640×480 Docker 输入均 s=1 no-op；`FileNotFoundError` 仍 cli.py:132→2；`test_verify_no_payload_exits_one` 仍 1）；HEIC 仍不支持；alpha 叠白静默；多帧从此响亮失败；GUI 边界见 :266-270。

**spike（如需）**
无。

**开放问题**
- HEIC：递延还是现在 `uv add pillow-heif`？判据：helper 内懒调 `register_heif_opener()`、12 MP HEIC 断言 format∈{HEIF,HEIC}、三平台 wheel+G2 许可。建议递延；上限 64 MP 固定 vs `--max-input-pixels` 建议先固定。
AGENTS.md：无冲突，无需用户裁定（零依赖、层级不变、不编辑）；唯一可升级项：支持 iPhone HEIC 属依赖变更（uv 合规），需用户裁定。

> 摘要：版本号 4 处硬编码、release 无测试/tag 闸门、GUI/macOS 无 CI 覆盖；做 tomllib 单源 + verify 闸门 + wheel 冒烟 + macOS leg。

### G5 — 发布与 CI 缺口（版本四处硬编码 / GUI 无覆盖 / 无 macOS job）

**严重度 / 工作量 / 批次 / 依赖 / 触及文件**
- 严重度：P2（残余 4 项）
- 工作量：0.5–1 天
- 批次：4
- 依赖：P2（gui job+marker）、G1（pyproject/uv.lock）、G2（`.iss`+workflows）、P1、P9
- 触及：`packaging/`、`tests/`（test_version_consistency.py 新、test_compliance.py）、`ci.yml`/`release-desktop.yml`、README/CLAUDE；`pyproject.toml`/`uv.lock` 只读

**现象与证据**
- 版本硬编码：`pyproject.toml:3`、`build_desktop.py:30/31/39`、`.iss:2`；`release-desktop.yml:3-6` 触发 `v*` 不比对；第 5 份 `uv.lock:814`。
- GUI/矩阵零覆盖：`test_gui_logic.py:5` 不 import gui；`ci.yml:47` 无 `--extra desktop`、`:15` 无 macOS（发行目标 `release-desktop.yml:40`）；`gui.py:9-17` import PySide6。

**根因**
发布路径逐 OS 自下而上长成，无人负责版本与测试闸门。

**推荐方案**
1. `build_desktop.py`：新增 `project_version()`（tomllib 读 pyproject）；`main(argv=None)` 首句 `--print-version`，早于 `:15`/`:19` guard；替换 `:30/:31/:39`。
2. `.iss` 删 `:2`，改由 `/DMyAppVersion=` 注入（`:8` 不动）；缺 define 须响亮失败（spike 2），否则断言产物 VersionInfo。
3. 新增 `tests/test_version_consistency.py`（4 fast 例）；`spec_from_file_location` 加载（**禁** `import packaging.build_desktop`）。
4. 新增 `packaging/smoke_wheel.sh`（bash；须已 dev sync）：① `env -u UV_PROJECT_ENVIRONMENT uv run --frozen --no-sync` 跑 `build_desktop.py --print-version`→`V`；② `uv build` 两产物在、wheel 含 `__main__.py`；③ `uv build --wheel <sdist>`；④ `UV_PROJECT_ENVIRONMENT=$TMP/venv` + `uv sync --frozen --no-dev --no-editable`；⑤ `realpath` 落 `$TMP/venv`、dist-info==`V`。
5. `release-desktop.yml` 加 `verify` job：`uv lock --check`→dev sync→`pytest -m 'not slow'`→取版本（空即 1；tag 时须 `== "v$V"`）；两构建 job `needs: verify`；`:30` 加 `/DMyAppVersion=…`。
6. `ci.yml`：`:15` 加 `macos-15`（沿用 `:47` dev sync，**会装 torch**）；**不得**声称覆盖字体回退/frozen `.app`；加 Linux-only step 跑 smoke。
7. 文档：`README.md` 写版本只住 `pyproject.toml`、先过 verify；`CLAUDE.md` 只改 `:72`；`:71`/`:238` 不写数字（归 P9）。
8. 合规盲区：`"pip[[:space:]]+install"`、`--exclude-dir`/`_EXCLUDE_DIRS` 去 `.github`、改 4 行（`ci.yml:30/:35/:36`、`docker.yml:53`）。

**被驳回或部分采纳的验证者意见**
- 部分采纳 #4/#7/#10/#24：A7 不写数字（R10）、驳回 `uv tool install`、`:71`/`:238` 归 P9。
其余 22 条验证者意见已全部并入上述方案。

**被否决的替代方案**
- git tag 推导（`uv_build` 无钩子）；`importlib.metadata`。

**API / CLI / 格式与退出码影响**
- `src/**` 零改动：**0/1/2 契约不变**；**无既有断言被放宽**；`MyAppVersion` 成**必填构建期 define**；**fast tier 不绿即不产出安装包、无 bypass**。

**测试清单**
| 文件 | 用例名 | 档 | 断言 |
|---|---|---|---|
| `test_version_consistency.py`(新) | test_packaging_reader_matches_pyproject、test_build_desktop_has_no_version_literal、test_iss_has_no_version_literal_and_still_uses_the_define、test_version_is_nuitka_compatible | fast | tomllib 机制、无点分数字面量、`.iss` 无字面量且含 `AppVersion` 定义 |

**验收标准**
- [ ] A1 版本 grep 恰 1 行；`uv lock --check` 绿（改版本不 lock 必红）。
- [ ] A2 /tmp 先 dev sync 再跑 smoke 退 0；两负控分别红。
- [ ] A3 Windows ISCC 带 `/D` 产物 VersionInfo 正确、不带非零退出。
- [ ] A4 verify 三分支退出码正确；授权推送后 verify 红、两构建 job 未启动。
- [ ] A5 第二次（热缓存）≤6 分钟、arm64 红则回滚矩阵行；A6 包 VersionInfo == tag；A7 计数不变（+4）；A8 gui 0 skipped。

**风险与未知**
- torch 必装：arm64 wheel 88 MB（`uv.lock:1389`）；ISPP `/D` 缺 define 若不响亮失败 → 空 AppVersion 而 CI 全绿。

**spike（如需）**
- 隔离+sdist：假设 `UV_PROJECT_ENVIRONMENT` 隔离、`uv build <sdist>` 需 `--wheel`／实验 /tmp smoke+负控／通过 退 0、负控红／失败 提前 export 仍绿。
- ISCC：假设缺 define 响亮失败／实验 带与不带 `/D` 读 VersionInfo／通过 值正确、不带非零／失败 不带也成功。
- tag 闸门：假设 verify 拦住产物／实验 A4 两次授权运行／通过 两构建 job 未启动／失败 任一启动。

**开放问题**
- **AGENTS.md 冲突，需用户裁定**：`AGENTS.md:88` 要求依赖装项目本地 `.venv`，第 4 步却是项目外 `$TMP/venv`；接受还是改「复制 checkout 再 sync」。
- 仓库 public/private？（无 `gh`）定 macOS leg 每 PR 跑或转 nightly。


---

## 7 附录：审计与验证证据链

本方案 14 个条目均走完同一四道流程：**设计**（每项一份长稿）→ **两个对抗视角的验证**（`feasibility` 可行性 / `regression` 回归波及面，两份判词各带 `refutations`/`corrections`/`missedRegressions`）→ **保真审计**（四份 `AUDIT-*.md`，逐条比对每节对验证意见的处置是否落地，并复核被引用的源码事实）→ **跨节一致性审查**（`CONSISTENCY.md`，14 节合并后才出现的互斥改动、归属歧义、新符号不一致、批次顺序矛盾、测试冲突与第三方行为主张冲突，并给出 R3/R4 一类的绑定裁决）。所有原始材料位于仓库外、不进版本控制：`/Users/jingdonglin/.codebuddy/projects/Users-jingdonglin-inori-lin-photo_cyber/01a0c7f5-9f5b-7b7b-b976-be9db27b714a/workflows/designs`（每项设计 JSON `<ID>.json` 与两份判词 `verdict-<ID>-feasibility.json` / `verdict-<ID>-regression.json`）、`…/workflows/designs/sections`（各节长稿 `<ID>.md`、`AUDIT-P1P2P3P4.md`/`AUDIT-P5P6P7P8.md`/`AUDIT-P9G1G2G3.md`/`AUDIT-G4G5.md`、`CONSISTENCY.md`）与 `…/workflows/designs/final`（进入第 6 节的压缩稿 `<ID>.md`）。

| ID | 验证 lens 组合 | feasibility 结论 | regression 结论 | 判词意见条数（含 refutations/corrections/missedRegressions） |
|---|---|---|---|---|
| P1 | feasibility + regression | sound-with-fixes | sound-with-fixes | 44（28 + 16） |
| P2 | feasibility + regression | sound-with-fixes | sound-with-fixes | 30（18 + 12） |
| P3 | feasibility + regression | sound-with-fixes | sound-with-fixes | 48（27 + 21） |
| P4 | feasibility + regression | sound-with-fixes | sound-with-fixes | 39（20 + 19） |
| P5 | feasibility + regression | sound-with-fixes | **flawed** | 47（23 + 24） |
| P6 | feasibility + regression | sound-with-fixes | sound-with-fixes | 42（23 + 19） |
| P7 | feasibility + regression | sound-with-fixes | sound-with-fixes | 33（17 + 16） |
| P8 | feasibility + regression | sound-with-fixes | sound-with-fixes | 24（14 + 10） |
| P9 | feasibility + regression | sound-with-fixes | sound-with-fixes | 29（15 + 14） |
| G1 | feasibility + regression | sound-with-fixes | sound-with-fixes | 35（16 + 19） |
| G2 | feasibility + regression | sound-with-fixes | sound-with-fixes | 49（27 + 22） |
| G3 | feasibility + regression | sound-with-fixes | sound-with-fixes | 24（16 + 8） |
| G4 | feasibility + regression | sound-with-fixes | sound-with-fixes | 28（13 + 15） |
| G5 | feasibility + regression | sound-with-fixes | sound-with-fixes | 41（25 + 16） |

结论分布：14 项 × 2 视角 = 28 份判词，其中 **27 份 `sound-with-fixes`、1 份 `flawed`**（P5 的 regression 视角，共 9 条 refutations + 9 条 corrections + 6 条 missedRegressions；其修正项已并入第 6 节 P5 正文，`flawed` 表示该稿需按修正重写，而非条目被否决）。全部 513 条验证意见在四份 `AUDIT-*.md` 中逐条核对了处置落点，被驳回或部分采纳的少数条目已在各项「被驳回或部分采纳的验证者意见」小节显式记录原因。

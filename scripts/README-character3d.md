# 自定义真人风格 3D 人物

网页运行直接读取 `web/assets/models/sweet-realistic.vrm`，不需要加载下面的建模模型。它是根据 GPT 生成的虚构成年亚洲女性照片重建的独立网格，包含标准人形骨骼与实际口型、眼睑形变。原人物和甜美人物的面部版仍单独保留。

## 资产与生成依据

- `data/avatars/generated/sweet-clean-v1.png`：高清肖像、面部纹理与身份参考。
- `sweet-3d-front-v1.png`：透明底全身 A 姿势，粉色开衫、米色长裤、白鞋。实际形状和 PBR 生成的输入。
- `sweet-3d-back-v1.png`：同人物背面，仅用于目测核对，不宣称使用了多视图重建。
- 各图片旁的 `.prompt.txt` 和 `generation-manifest.json` 保存提示词与哈希。
- `web/assets/models/sweet-realistic.source.json` 保存最终模型哈希、各生成步骤参数、耗时与来源。

## Apple Silicon 离线制作流程

已安装的建模环境与实时语音环境分离。使用 AssetFurnace 提交 `91879333e88a0571945b15b0e21e4bc95ec59e31`，Hunyuan MLX 两个环境使用其自带 `uv.lock`；面部和绑定环境的已验证版本见同目录 `requirements-character3d-*.lock.txt`。

准备源码与环境：

```bash
git clone https://github.com/Bingeljell/image-to-3dlab third_party/assetfurnace
git -C third_party/assetfurnace checkout 91879333e88a0571945b15b0e21e4bc95ec59e31
uv sync --project third_party/assetfurnace/hunyuan_mlx/shape
uv sync --project third_party/assetfurnace/hunyuan_mlx/paint
uv run --project third_party/assetfurnace python third_party/assetfurnace/scripts/bootstrap_autorig.py --build-only --yes
uv venv --python 3.11 .venv-3d
uv pip install --python .venv-3d/bin/python -r scripts/requirements-character3d-face.lock.txt
.venv-3d/bin/python scripts/download-character3d-models.py
```

权重约 15.27 GB，下载器固定 revision 并核对 LFS SHA256，可断点续传。原始下载记录在 `models/character3d-sources.json`。还需要 Blender 4.5 LTS、MediaPipe 官方 face/hand landmarker task 与 canonical face OBJ，以及 MakeHuman 的 CC0 手部模板。当前机器已经准备完毕，相关输入保存在 `models/character3d-work/`。模板源码版本见最终模型来源文件。

制作顺序（较重的生成请先停止实时语音服务并卸载 LM Studio 模型，释放统一内存）：

```bash
third_party/assetfurnace/hunyuan_mlx/shape/.venv/bin/python scripts/build-character3d-shape.py
.venv-3d/bin/python scripts/extract-character3d-face.py
.venv-3d/bin/python scripts/extract-character3d-face.py --source data/avatars/generated/sweet-clean-v1.png --output models/character3d-work/portrait-landmarks.json --full-frame
.venv-3d/bin/python scripts/extract-character3d-hands.py
.venv-3d/bin/python scripts/refine-character3d-hands.py
third_party/assetfurnace/hunyuan_mlx/paint/.venv/bin/python scripts/build-character3d-paint.py
.venv-3d/bin/python scripts/build-character3d-face.py
/Applications/Blender.app/Contents/MacOS/Blender --background --python scripts/prepare-character3d-face-blender.py
.venv-3d/bin/python scripts/build-character3d-rig.py
./scripts/build-character3d-final.sh
```

形状采用原生 MLX / Metal，8 位权重、30 步；约 206 万面原始结果简化到约 12 万面。手部用每只 21 个照片关键点拟合 CC0 解剖拓扑，保证手指可绑定。PBR 阶段生成 4K 材质；面部使用 468 点拓扑、独立眼球与口腔和细分后的实际 morph target。SkinTokens 使用 PyTorch MPS 生成骨架和蒙皮，再做权重清理，转换标准 T 姿势并导出 VRM 1。

在这台 M4 / 24GB 上，形状生成约 966 秒、GPU 峰值约 9.74 GiB；PBR 约 1105 秒、峰值约 21.78 GiB；骨架与权重清理约 314 秒。它们是一次性离线操作，实时浏览器不运行生成网络。PBR 峰值接近本机内存容量，应单独执行。

## 动作与验证

`web/assets/motions/conversation.json` 是上游预生成的 Kimodo 动作，已转换为标准骨骼世界四元数。网页在本地将其重定向到自定义人物，结合 IK、过渡、脚底高度与肢体间距约束。动作来源和许可单独记录在相邻 `source.json`。无需下载 Kimodo 模型。

```bash
.venv-3d/bin/python scripts/verify-character3d-geometry.py
node scripts/verify-body-motion.mjs
.venv/bin/python scripts/verify-text-dialogue.py
./scripts/verify-all-mac.sh
.venv/bin/python scripts/verify-avatar-switching.py
```

几何测试检查连接带边界、三角形朝向与整数坐标轴；组装时检查只保留眼睛和嘴的三个开口，以及所有 morph 坐标有限。骨骼测试使用真实 VRM 加载器与生产重定向代码，检查挥手、腿部位移和单位四元数。语音、文字与切换测试建立真实本地连接。网页还需目测所有动作、播放音频时的口型、人物切换、控制台与响应布局。

后续精修由 `polish-character3d-blender.py` 完成，已包含在 `build-character3d-final.sh`：对衣料与头发表面做 16 组 Taubin 去噪，位移最多 8mm，保护面部和手指；分离皮肤、头发、针织、长裤和鞋的材质；增加 480 条确定性细发丝，并清除长发上的手臂误绑定。运行时以本地生成的柔光环境、色调映射、软阴影、各向异性过滤和针织法线呈现，不访问外部 HDR 或 CDN。

这是照片生成的实时人物，不等于影视级人工雕刻角色：细发丝跟随原蒙皮，没有独立发丝物理；主要发型与衣服仍保留单图重建误差。口型按实际播放音频的能量和频谱驱动，尚非中文音素精确对齐；`sad`、`relaxed` 目前保留接口而未制作独立有效形变。实际实现的是眨眼、微笑与三种口型。

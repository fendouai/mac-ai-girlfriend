# Apple Silicon Mac：面部版与 3D 肢体版

安装、启动和常见问题以 [Mac 版首页](README.md) 为入口；改写前说明完整保留在 [README_ORIGINAL.md](README_ORIGINAL.md)。本文继续保存素材、渲染与验证细节。

这台机器为 Apple M4、24GB 统一内存。完整语音后端使用本地 SenseVoice、LM Studio 和 CosyVoice2 克隆音色；不需要云端 API Key。人物可在同一网页切换，所有网页依赖与 3D 模型均在本地。

## 使用两个版本

运行 `./scripts/start-mac.sh`，访问 http://localhost:7860。

- **面部版**：原人物或甜美人物两套干净基准图，LivePortrait 离线制作短暂眨眼，身体与背景保持静止；新语音由原版 Wav2Lip256/Core ML 实时驱动嘴型，WebRTC 同轨播放声音和视频。
- **肢体版 · 3D**：由 GPT 生成的成年甜美亚洲女性照片重建的自定义 VRM 人物，52 根标准骨骼，支持挥手、点头、思考、讲述、鞠躬、走动和跳舞，包含眼睑、微笑与实际口型形变；思考动作使用双骨骼逆向运动学，录制动作按人物体型做手臂避让。
- 可点击动作按钮预览，也可通过“文字交流”聊天或要求人物做动作。**试听问候**使用真实本地克隆语音和对话引擎，不启用硬件麦克风；**点击开始对话**才申请麦克风。
- 切换版本或面部人物时结束当前语音会话，点击开始即可重新对话。连接会主动释放，避免快速切换耗尽 WebRTC 会话名额。
- 版本也可通过 URL 指定：`/?avatar=face`、`/?avatar=body`；之后的切换会同步更新 URL。

面部版保留原人物与甜美人物两套照片；3D 版基于甜美人物的高清肖像与全身正面图进行建模，具有独立网格、4K 材质与骨骼蒙皮。模型来源、哈希和参数见 `web/assets/models/sweet-realistic.source.json`，完整流程见 [3D 制作记录](scripts/README-character3d.md)。背面图用于视觉核对，未用于多视图重建。旧 pixiv 示例只保留作参考，网页默认加载自定义人物。

3D 版口型由实际播放音频的能量和频谱驱动，保持声音与嘴部同一播放时钟；当前不宣称具备中文音素级精确对齐。它不调用 Wav2Lip，也不使用云端动作分类服务。面部版继续保留原版 Wav2Lip 嘴型。

面部版说话合成使用每个人物独立的嘴唇位置与倾角（`data/avatars/mouth-profiles.json`）。生成口型通过多频段融合贴回：鼻翼、眼睛、下巴轮廓和外围皮肤细节保留原图，唇部保留实际模型运动，肤色修正只取周围皮肤并做时间平滑。开始/结束说话用最多两帧的局部过渡，打断时立即清除旧口型状态；不对快速口型做帧平均，也不改变音频时间线。

## 安装与启动

```bash
./install.sh
# 等价：./scripts/install-mac.sh
```

安装脚本使用 uv 创建 Python 3.11 环境并安装锁定依赖，下载作者声音模型、转换 Core ML，并在缺少面部素材时准备两套形象。第一次需要联网，模型和准备结果会复用。

面部素材准备使用固定提交的 [LivePortrait](https://github.com/KlingTeam/LivePortrait)；下载脚本按固定 Hugging Face revision、尺寸和 LFS SHA256 校验权重，分段缓存可续传。它只在离线预处理时运行，实时对话不加载该模型。InsightFace 检测和关键点在 CPU，LivePortrait 主要运行在 MPS，暂不支持的 3D grid sampler 使用 PyTorch CPU 回退。

本地大模型复用 LM Studio：

```bash
lms load dolphin3.0-llama3.1-8b --context-length 4096
lms server start --port 8200
./scripts/start-mac.sh
```

启动预热期间 `/api/health` 的 `engines_ready` 为 false；变为 true 后即可对话。Ctrl+C 停止启动脚本创建的服务；LM Studio 单独运行。

## 加速设备

| 部分 | 执行方式 |
|---|---|
| 本地大模型 | LM Studio / Metal |
| 中文语音识别 | SenseVoiceSmall CPU，量化并预热 |
| 克隆语音 | CosyVoice2 语音解码 MLX / Metal FP16、声学估计 Core ML GPU、声码器 CPU |
| 面部嘴型 | 原版 Wav2Lip256 权重转换 Core ML，Apple CPU/GPU/Neural Engine 由系统调度 |
| 面部视频编码 | VideoToolbox H.264，25fps |
| 3D 人物 | 浏览器 Three.js / WebGL，52 根标准骨骼 |
| 3D 音频 | 本地 PCM → AudioWorklet → 同一输出 Analyser 驱动嘴部 |

语音优化保留原版 CosyVoice2、参考音色和采样逻辑，缓存参考录音特征。语音 token 解码使用本地 MLX 的 Qwen2 实现，复用原权重并采用 FP16；移除未使用的文字词表投影，释放重复的 PyTorch 解码层并限制 MLX 缓存。FP32 对照和 FP16 语音输出均有验证脚本。将 `tts.speech_backend` 改为 `torch` 可回到 PyTorch 路径。

打断会取消 token 生成、在声学估计步骤之间退出，并清理队列；各 WebSocket 独立保存 VAD、历史、打断状态和数字人会话，只共享模型权重。整段语音仍预先生成，保持连续播放，不会为了首声速度直接打开可能欠缓冲的流式播放。界面区分“正在想怎么回答”和“正在准备声音”。2026-10-19 本机约 45 字回复，收到音频由约 19 秒降至约 8.4 秒，实际面部 WebRTC 首声约 9 秒；耗时随文字长度和系统负载变化。

详细结果与复现方法见 [回复加速验收](scripts/ACCEPTANCE-REPLY-SPEED.md)。

默认语音人设现已改为通常 10～24 字、最多两句；`config.mac.yaml` 的 `llm.max_reply_chars: 40` 与 `max_reply_sentences: 2` 在流生成阶段限制长度，`max_tokens` 为 64。网页已有的旧人设也附加当前短回复规则。需要展开时说“继续”，由下一轮承接，不自动连续生成长篇；连续播放路径保持整段预缓冲。

## 素材与许可

- `data/avatars/generated/original-clean-v1.png`：以仓库原图为参考生成的干净基准图。
- `data/avatars/generated/sweet-clean-v1.png`：新设计的成年甜美人物。
- `generation-manifest.json`：完整生成提示词与静态素材说明。
- `third_party/livetalking/data/avatars/hex_clean_original`、`hex_clean_sweet`：各 200 帧，含两次短暂眨眼。仅眼部使用 LivePortrait，嘴、身体和背景保持原图像素；嘴部只在运行时进行 Wav2Lip 推理。
- `web/vendor/`：固定版本 three.js / three-vrm，MIT 许可原文随附，运行不依赖 CDN。
- `web/assets/models/`：自定义 VRM、生成过程与第三方组件来源；旧示例另有独立许可。
- 声音权重来自[作者模型包](https://huggingface.co/datasets/hexgeek/hex-ai-girlfriend-datasets)，下载脚本校验 ZIP CRC。
- 原先的 `hex_original` 静态形象和 `hex_original_motion` 演示录屏衍生形象仍可手动选择，但不再是默认。公开金色礼服人物不是 README 原图人物。

## 验证

空闲时执行：

```bash
./scripts/verify-all-mac.sh
```

依次验证真实语音识别、本地模型回复和克隆语音，WebRTC 连续音频、中断，两套面部素材的身体静止及循环衔接，浏览器音频播放器在 16/44.1/48kHz 输出下的连续性，以及 3D 使用的浏览器语音传输路径。测试会建立真实会话，请在自己的对话结束后运行。

骨骼重定向与真实文字交流可运行 `node scripts/verify-body-motion.mjs`、`.venv/bin/python scripts/verify-text-dialogue.py`，面部切换回归运行 `.venv/bin/python scripts/verify-avatar-switching.py`。

嘴周融合的定量回归运行 `.venv/bin/python scripts/verify-mouth-compositor.py`；真实说话视频、鼻部稳定性与解码帧率运行 `.venv/bin/python scripts/verify-face-speaking.py`。同一批真实 Wav2Lip 输出的新旧对比由 `.venv/bin/python scripts/compare-mouth-compositing.py` 生成，结果在 `logs/*mouth-comparison.mp4`。这些边界像素指标反映原图保留程度，不是主观自然度评分。

3D 动作还需浏览器验证：切换肢体版后依次预览动作，再试听问候，确认手臂/身体骨骼运动和声音驱动嘴型。实际骨骼世界坐标和输出音频的峰值可从 canvas 的 `data-rig` 读取；该数据用于诊断，不能替代视觉质量检查。精修版增加了表面去噪、分区材质、480 条蒙皮细发丝和本地柔光环境，但发丝没有独立物理模拟；口型尚非中文音素级精确对齐。

最近语音验收结果见 `logs/acceptance-final.log`；人物截图和浏览器实际语音驱动证明保存在 `logs/`。

运行时离线验证（只约束本次 Python 进程，不修改系统网络设置）：

```bash
PYTHONPATH="$PWD/scripts/offline_guard:${PYTHONPATH:-}" ./scripts/start-mac.sh
```

该钩子拒绝公网 DNS/HTTP。不要在下载依赖或模型时启用。网页所需代码与模型均为同源本地文件。

## Docker

Dockerfile / compose.yaml 仅保留 CPU 联调模式，使用固定文本和正弦波，不代表完整功能。当前机器未安装 Docker，容器未构建验证。

Mac Linux 容器不能直接使用原生 Core ML/MPS，因此完整实时版本采用原生 Mac 部署。[Docker GPU 官方说明](https://docs.docker.com/desktop/features/gpu/) 中 NVIDIA GPU 透传面向 Windows WSL2。

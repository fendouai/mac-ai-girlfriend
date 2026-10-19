<!--
  Hex AI Girlfriend — 本地实时数字人语音对话
  Copyright (C) 2026 Hex-电脑课堂
  YouTube: https://www.youtube.com/channel/UC2s3nBn_v4So9-8GQORMDhA
  SPDX-License-Identifier: GPL-3.0-or-later
-->
# Mac AI Girlfriend · Apple Silicon 本地数字人

基于 Hex AI Girlfriend 适配的 Mac 本地语音数字人：SenseVoice 识别中文，LM Studio 生成回复，CosyVoice2 使用参考音色说话。网页支持照片面部版和可做全身动作的 3D 肢体版，也支持文字交流、试听问候和插话打断。

**本 README 以原生 Mac 部署为主。** 改写前的 README 已完整保存为 [原版说明（Windows / WSL2 / Ubuntu）](README_ORIGINAL.md)。其他入口：[Mac 实现细节](README_MAC.md) · [3D 人物制作记录](scripts/README-character3d.md) · [历史英文说明](README_EN.md)。

## 目录

- [环境与资源](#环境与资源)
- [安装与启动](#安装与启动)
- [使用面部版与-3d-版](#使用面部版与-3d-版)
- [Mac 加速与声音路径](#mac-加速与声音路径)
- [配置](#配置)
- [延迟与环境杂音](#延迟与环境杂音)
- [验证与排错](#验证与排错)
- [Docker 的用途](#docker-的用途)
- [项目结构](#项目结构)
- [素材来源与许可](#素材来源与许可)

## 环境与资源

| 项目 | 说明 |
|---|---|
| 系统 | Apple Silicon Mac（`arm64`）；安装脚本会检查架构 |
| 已验证机器 | Apple M4、24GB 统一内存、macOS 26.6.2；这是实测配置，不是最低配置保证 |
| Python | 3.11，由 `uv` 创建项目内的 `.venv` |
| 本地工具 | `git`、`uv`、`ffmpeg`；LM Studio 及其 `lms` 命令 |
| 浏览器 | 支持 WebRTC、AudioWorklet 和 WebGL 的浏览器；使用 localhost 访问麦克风 |
| 模型 | SenseVoiceSmall、CosyVoice2、Wav2Lip、silero-vad，以及 LM Studio 中的对话模型 |
| 人物资源 | `data/avatars/generated/`、生成后的面部帧，以及 `web/assets/models/sweet-realistic.vrm` |

首次安装、模型下载与 Core ML 转换需要联网和额外磁盘空间，准备时间取决于网络与机器。准备完成后，对话推理和网页人物资源均可在本机运行，不需要云端 API Key。模型权重和预处理缓存不全部随 Git 分发。

使用包含当前 `scripts/`、`web/assets/` 和 `data/avatars/` 的完整项目目录。3D 成品模型缺失时，需要按 [3D 制作记录](scripts/README-character3d.md) 单独重建；普通安装脚本不会重新执行图像生成和完整 3D 建模。

## 安装与启动

以下命令均在项目根目录执行。

获取 Mac 版项目：

```bash
git clone https://github.com/fendouai/mac-ai-girlfriend.git
cd mac-ai-girlfriend
```

### 1. 准备工具并安装依赖

先准备 `git`、`uv` 和 `ffmpeg`。如果已经使用 Homebrew，可以执行：

```bash
brew install git uv ffmpeg
```

然后安装项目：

```bash
./scripts/install-mac.sh
```

在 macOS 上执行 `./install.sh` 也会进入同一安装流程。脚本使用 [锁定依赖](requirements-mac.lock.txt)，安装 Python 环境、准备声音模型、转换 Core ML，并在缺少面部缓存时生成形象帧。已有模型与缓存会复用。

若终端提示脚本不可执行：

```bash
chmod +x install.sh scripts/install-mac.sh scripts/start-mac.sh scripts/start-avatar-mac.sh
```

### 2. 准备本地大模型

在 LM Studio 中先下载模型，使用 `lms ls` 确认可用。默认配置使用 `dolphin3.0-llama3.1-8b`：

```bash
lms ls
lms load dolphin3.0-llama3.1-8b --gpu max --context-length 4096 \
  --identifier dolphin3.0-llama3.1-8b --yes
lms server start --port 8200 --bind 127.0.0.1
```

如果换用其他模型，同步修改 [config.mac.yaml](config.mac.yaml) 中的 `llm.model`，使其与服务返回的模型 ID 一致。不要把尚未下载的模型名称直接当作已安装模型使用。

若提示找不到 `lms`，先完成 LM Studio 的 CLI 安装/路径配置，确认 `lms --help` 可运行。

### 3. 启动数字人和网页服务

```bash
./scripts/start-mac.sh
```

浏览器打开 [本地网页](http://localhost:7860/?avatar=face)。首次启动会预热语音模型；用下面的命令确认就绪：

```bash
curl -fsS http://127.0.0.1:7860/api/health
```

正常就绪结果：

```json
{"ok":true,"engines_ready":true,"startup_error":null}
```

`engines_ready: false` 表示仍在预热；若 `startup_error` 非空，先处理该错误。网页能打开不代表模型已经加载完成。

### 4. 停止、重启与日志

在运行启动脚本的终端按 **Ctrl+C**，脚本会停止它创建的网页和数字人进程。再次运行 `./scripts/start-mac.sh` 即可重启。LM Studio 独立运行，需要时用 `lms server stop` 单独停止其 API 服务。

数字人日志：

```bash
tail -f logs/avatar-mac.log
```

需要把网页、识别与语音生成日志保存到文件时：

```bash
./scripts/start-mac.sh > logs/mac.log 2>&1
```

再在另一个终端执行 `tail -f logs/mac.log`。改动后端配置后重启服务；改动前端代码后刷新页面。

## 使用面部版与 3D 版

| 版本 | 人物与驱动 | 当前能力与限制 |
|---|---|---|
| [面部版](http://localhost:7860/?avatar=face) | 原人物、甜美人物两套干净照片；原版 Wav2Lip256 / Core ML 驱动嘴部 | 自然眨眼、说话口型；身体和背景保持静止。大幅口型、牙齿和表情联动仍受原模型限制 |
| [肢体版 · 3D](http://localhost:7860/?avatar=body) | 根据 GPT 生成的虚构成年亚洲女性图片重建的自定义 VRM，52 根标准骨骼 | 挥手、点头、思考、讲述、鞠躬、原地走动和跳舞；有眼睑与嘴部形变。口型由实际播放音频驱动，尚非中文音素级精确对齐 |

- **试听问候**：运行真实本地对话和克隆语音，不开启硬件麦克风。
- **点击开始对话**：授予麦克风权限后进行语音聊天；界面区分聆听、生成和播放状态。
- **文字交流**：输入文字，也可以要求 3D 人物执行已支持的动作。
- **继续展开**：默认先说一小段；需要更多内容时说或输入“继续”，再生成下一段，不自动连发整篇。
- **动作按钮**：直接预览 3D 动作，不必等待模型理解指令。
- **切换版本或面部人物**：会结束当前语音会话；切换后重新开始对话。

面部版的眨眼素材由 LivePortrait 离线生成，实时说话不加载 LivePortrait。嘴周使用按人物对齐的局部融合，保留鼻翼、脸颊和下巴细节。[嘴周融合验收](scripts/ACCEPTANCE-FACE-MOUTH.md) 记录了方法和回归数据。

3D 成品是图片重建、材质、骨骼绑定和后续修整的结果；图片本身不包含可直接播放的 3D 骨骼。模型制作、来源与当前质量边界见 [制作记录](scripts/README-character3d.md)。

## Mac 加速与声音路径

| 环节 | 本机执行方式 |
|---|---|
| 对话 LLM | LM Studio / Metal |
| 语音识别 | SenseVoiceSmall / CPU，量化并预热 |
| 克隆语音 token | 原 CosyVoice2 权重，MLX / Metal FP16，KV cache 与原采样逻辑 |
| 声学估计 | Core ML GPU；不适用的输入保留 PyTorch 回退路径 |
| 声码器 | HiFT / CPU |
| 面部口型 | Wav2Lip256 / Core ML，系统调度 Apple CPU、GPU 或 Neural Engine |
| 视频编码 | VideoToolbox H.264，目标 25fps |
| 3D 渲染 | 本地 Three.js / WebGL，音频分析驱动嘴部 |

面部版将生成声音送入 LiveTalking，声音和人物视频通过同一条 WebRTC 连接回传。3D 版通过浏览器 AudioWorklet 播放 PCM，并使用同一播放时钟驱动嘴部。

各 WebSocket 独立保存会话、VAD、历史和取消状态，共享已预热的模型。打断会终止旧语音任务，清理队列并停止旧口型。MLX 转换后释放重复的 PyTorch 解码层，并限制缓存占用，减少统一内存压力。

## 配置

Mac 默认读取 [config.mac.yaml](config.mac.yaml)，人设位于 [persona.md](persona.md)。

| 配置 | 用途 |
|---|---|
| `llm.base_url`、`llm.model` | 本地模型 API 地址和模型 ID |
| `llm.max_tokens` | 最大生成 token 数；不等同于汉字数或音频秒数 |
| `llm.max_reply_chars`、`llm.max_reply_sentences` | 语音回复上限，默认最多 40 字、两句；通常提示模型只说 10～24 字 |
| `tts.ref_wav`、`tts.ref_text` | 参考录音及其逐字文本，换音色时一起修改 |
| `tts.speech_backend` | 默认 `mlx`；改为 `torch` 可使用 PyTorch 路径 |
| `tts.speech_dtype` | MLX 默认 `float16`，也可使用 `float32` 对照 |
| `tts.chunk_ms` | 默认 `0`：整段合成后播放，以保证连续性 |
| `avatar.id` | 默认面部人物；网页可以选择另一套人物 |
| `vad.min_speech_ms` | 确认持续人声后才触发开口，当前 350ms |
| `vad.min_silence_ms` | 连续安静多久才判断说完，当前 600ms |
| `memory.turns` | 保存最近对话的轮数 |

网页设置中的人设、音频设备和噪声门会保存在当前浏览器的本地存储中。网页人设可以覆盖服务端人设；修改 `persona.md` 后，若仍显示旧人设，检查网页设置。

[config.mac-lite.yaml](config.mac-lite.yaml) 是独立的 Whisper / macOS 系统语音调试配置，音色与完整模式不同；默认启动脚本不会读取它。[config.yaml](config.yaml) 留给旧版部署；[config.docker.yaml](config.docker.yaml) 使用测试引擎。

## 延迟与环境杂音

应区分 **等你说完**、**生成文字**、**生成语音** 和 **实际播放** 四段耗时。麦克风电平条显示噪声门处理前的原始音量，因此安静时仍有小幅波动，不等于后端正在识别人声。

当前流程需要连续约 600ms 的非人声才判断句子结束。持续背景人声、电视声音或扬声器回声可能延后断句，也可能被当成插话取消回复。风扇底噪和短促敲击不一定触发 VAD；实际效果取决于音量和输入设备。浏览器已请求回声消除、降噪和自动增益，但不能据此保证过滤所有环境声。

网页噪声门默认约 `-50 dBFS`，实际值可能被本地保存的设置覆盖。调节时观察“不说话”和“正常轻声说话”的电平差，门限应高于底噪、低于轻声语音。门限过高会丢失轻声和字尾。一次本地合成样本测试中，轻背景人声让同一句话的结束判定延后约 4.6 秒，见 [杂音诊断](scripts/DIAGNOSIS-NOISE.md)。

长回复本身也慢。2026-10-19 加速基准中，约 45 字回复的 PCM 返回由约 19 秒降到约 8.4 秒，实际面部版首声约 9 秒，视频约 25fps；之后实际对话曾产生 160 多字回复，文字生成约 18 秒、语音合成约 39 秒。**这些是启用短回复策略前的样本，不是固定延迟保证。**

因此当前已进一步启用短回复策略：通常 10～24 字，最多两句、40 字，在 LLM 流生成阶段就按句尾和长度停止；旧版网页保存的人设也会附加该规则。长内容按对话轮次展开，等用户说“继续”后才生成下一小段。它不是自动分块朗读长文，也没有把现有连续音频路径改成逐句碎片播放。

实现和测试见 [短回复验收](scripts/ACCEPTANCE-SHORT-REPLIES.md)。

当前保留整段预缓冲播放。不要只把 `chunk_ms` 改为正数就认为可以兼顾即时出声和连续性，需同时验证生成吞吐、预缓冲和口型。详细基准见 [回复加速验收](scripts/ACCEPTANCE-REPLY-SPEED.md)。

## 验证与排错

### 基础检查

```bash
curl -fsS http://127.0.0.1:7860/api/health
curl -fsS http://127.0.0.1:8200/v1/models
uv pip check --python .venv/bin/python
```

| 端口 | 服务 |
|---|---|
| `7860` | 网页、WebSocket、健康检查、`/lt/` 反向代理 |
| `8010` | LiveTalking / WebRTC 数字人后端 |
| `8200` | LM Studio 本地模型 API |

### 本地端到端与回归

结束自己的语音对话后，串行运行测试，避免占用人物会话名额或互相影响耗时：

```bash
# 录音输入 → VAD → 识别 → 本地模型 → 克隆语音
HEX_VERIFY_TRANSPORT=browser .venv/bin/python scripts/verify-voice.py

# 实际面部版：文字 → 克隆语音 → WebRTC 音视频、帧率与嘴部运动
.venv/bin/python scripts/verify-fast-face-e2e.py

# 连续音频与播放中打断
.venv/bin/python scripts/verify-playback.py
.venv/bin/python scripts/verify-interrupt.py

# 双连接隔离
.venv/bin/python scripts/verify-session-isolation.py

# 短回复上限、旧人设覆盖与“继续”
.venv/bin/python scripts/verify-reply-budget.py
.venv/bin/python scripts/verify-short-replies.py

# 两套素材和嘴周融合
.venv/bin/python scripts/verify-face-assets.py
.venv/bin/python scripts/verify-mouth-compositor.py
```

数值对照、Flow 取消和性能测试的完整命令见 [加速验收](scripts/ACCEPTANCE-REPLY-SPEED.md)。`scripts/verify-all-mac.sh` 还包含浏览器播放器测试，需要可用的浏览器测试依赖。协议测试不能代替对人物表情、材质和动作自然度的人工观察；3D 应在网页上逐个预览动作并试听。

### 常见问题

| 现象 | 检查方式 |
|---|---|
| 网页打开但不能回复 | 先看 `/api/health`，再确认 LM Studio 的 `8200` 服务和模型 ID |
| 只有声音、没有人物 | 检查 `logs/avatar-mac.log`、`8010`、形象帧和 `coords.pkl` 是否齐全 |
| 人物有动作但无声音 | 点击“试听问候”允许播放，检查网页静音和系统输出设备 |
| 麦克风无输入 | 使用 localhost，检查浏览器及 macOS 麦克风权限、网页输入设备 |
| 没说话时电平仍在动 | 电平是门前信号；先观察是否真的出现用户发言或打断，再校准噪声门 |
| “生成中”很久 | 看 `[timing]` 日志，区分 LLM、TTS、合成锁等待；长回复明显更慢 |
| 轻声/字尾丢失 | 检查噪声门是否过高，避免只为消除电平波动而提高门限 |
| 快速切换后人物连不上 | 关闭多余预览页，等待旧连接释放；默认最多两个人物会话 |
| 统一内存压力大 | 减少同时打开的模型和预览，检查是否同时运行建模环境或较大的 LM Studio 模型 |
| 换人物后口型错位 | 核对形象资源及 `data/avatars/mouth-profiles.json`，参考图 SHA 不符会回退融合方式 |

### 运行时离线验证

以下命令只限制本次 Python 进程的公网访问，不改变系统网络设置：

```bash
PYTHONPATH="$PWD/scripts/offline_guard:${PYTHONPATH:-}" ./scripts/start-mac.sh
```

该钩子阻止公网 DNS/HTTP，允许本机服务互通。下载依赖、模型和准备素材时不要启用它。

## Docker 的用途

当前 [Dockerfile](Dockerfile) 和 [compose.yaml](compose.yaml) 仅用于 **CPU 测试引擎联调**：固定文字和测试音频，不包含完整语音克隆、面部口型或 Mac GPU 加速。在这台机器上未完成容器构建验证。

完整版本使用原生 Mac 运行，调用 MLX、MPS、Core ML 和 VideoToolbox。当前容器方案不能提供这些原生加速路径，因此 Docker 不作为本教程的默认安装方式。

## 项目结构

```text
config.mac.yaml                 Mac 默认运行配置
persona.md                      服务端人设
requirements-mac.lock.txt       Mac 依赖锁
scripts/install-mac.sh          安装与模型/素材准备
scripts/start-mac.sh            启动入口
src/                            FastAPI、编排、识别、语音和 Apple 加速
web/                            网页、音频采集/播放、面部和 3D 展示
web/assets/models/              自定义 VRM、材质与来源记录
data/avatars/                   干净人物图、生成提示词和嘴周配置
models/                         本地模型与 Core ML 包
third_party/livetalking/        原版口型后端及面部帧缓存
third_party/CosyVoice/          语音克隆实现
logs/                           本机日志、验收数据和测试媒体
README_ORIGINAL.md              改写前 README 的完整归档
README_MAC.md                   更详细的 Mac 实现与素材说明
```

## 素材来源与许可

保留原项目作者 [Hex-电脑课堂](https://www.youtube.com/channel/UC2s3nBn_v4So9-8GQORMDhA) 的署名。

- 原人物干净图以仓库原图为参考重新生成；甜美人物为新设计的虚构成年人。提示词与来源保存在 [人物生成记录](data/avatars/generated/generation-manifest.json)。
- 面部眨眼离线使用 LivePortrait；实时口型使用 Wav2Lip / LiveTalking。
- 3D 图像重建、绑定、材质、动作来源及相关许可单独记录在 [制作记录](scripts/README-character3d.md)、[模型来源](web/assets/models/sweet-realistic.source.json) 和 [模型说明](web/assets/models/NOTICE.md)。
- 语音模型下载来源与校验方式见 [Mac 细节](README_MAC.md)。克隆声音需具备对应使用授权。

| 组件 | 本项目中的用途 |
|---|---|
| CosyVoice2 | 参考音色克隆与语音生成 |
| SenseVoice / FunASR、silero-vad | 语音识别与端点检测 |
| LM Studio、MLX / MLX-LM | 本地对话模型及 Apple GPU 语音解码 |
| LiveTalking、Wav2Lip、LivePortrait | 人物视频、口型与离线眨眼素材 |
| Three.js、three-vrm | 浏览器 3D 人物渲染与骨骼 |
| hf-realtime-voice | 前端语音交互与音频管线参考 |

项目采用 [GPL-3.0-or-later](LICENSE)，各第三方组件、模型和素材另遵循其附带许可；模型许可不能直接等同于项目代码许可。原版说明中的作者介绍、旧部署步骤与第三方链接完整保留在 [README_ORIGINAL.md](README_ORIGINAL.md)。

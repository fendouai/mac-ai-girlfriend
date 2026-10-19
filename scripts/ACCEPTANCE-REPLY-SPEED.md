# 本地回复加速验收 · 2026-10-19

## 已实现

- 保留原版 CosyVoice2 和 `data/prompt1.mp3` 参考音色。Qwen2 语音 token 解码迁移至已安装的本地 MLX / Metal，实现 KV cache，使用 FP16 权重；不调用在线 TTS，也不更换成系统声音。
- PyTorch 回退路径跳过 Qwen 的 151936 项文字词表输出，直接使用 transformer hidden state 和原有语音输出头。解码时没有使用的文字 logits 不再计算。
- MLX 路径在转换后释放 PyTorch 的重复 24 层 decoder，保留 prompt embedding 和兼容的 encoder 接口；MLX 缓存限制为 256 MiB。该 decoder 实测活动内存约 739 MB。
- 每回合独立取消事件。排队中的取消请求可以退出；生成中每个 token 检查取消；Flow 的估计器各步检查取消；取消后清理 token/cache 字典再释放合成锁。旧音频不再只“丢输出却继续完整计算”。
- 每个 WebSocket 独立编排状态、历史和 VAD，只共享已预热的推理模型。旧标签页关闭不会重置新标签页或打断其数字人。
- 仍使用完整 WAV 预缓冲，保留既有连续播放与口型同步路径。生成中向页面发送阶段状态，避免无提示地等待。`chunk_ms` 保持 0，未直接开启欠缓冲的流式播放。

## 延迟

同机真实 WebSocket 文字输入，使用原本地 LLM 和克隆语音；首音频指客户端收到 PCM，不等于物理扬声器首声。

| 场景 | 优化前 | 优化后 |
|---|---:|---:|
| 12 字短句，收到 PCM | 6.60s | 3.74s（含实际面部视频连接） |
| 约 45 字长句，收到 PCM | 19.00s | 8.42s（含实际面部视频连接） |
| 打断长句后回复“好的。”，收到 PCM | 20.04s | 2.57s |
| 新短句等待旧 TTS 锁 | 13.02s | 0s（该次打断测试） |

受控长句第一次优化复测：语音 token 约 11.86s → 2.48s，完整合成约 16.63s → 6.16s。不同采样运行的音频长度会略变，这些是样本，不是固定耗时保证。

最终实际面部端到端测试：短句约 4.43s 收到第一帧有声 WebRTC 音频；长句约 9.01s。PCM 就绪到 WebRTC 首声约 0.60–0.84s。视频解码约 24.70fps，有真实嘴部帧间运动。

Flow 中途取消测试：约 194ms 返回取消完成，新短句约 4.27s 返回音频。该路径没有异常堆栈，旧任务不再持续计算完整句子。

## 正确性与回归

- PyTorch 跳过文字 head：30 步 hidden state 完全一致。
- 实际 CosyVoice 权重和参考 prompt，MLX FP32 的 30 步 teacher-forced 语音 logits 最大差约 `1.43e-5`，greedy token 一致率 100%。FP16 logits 余弦相似度约 `0.9999994`，该样本 greedy token 一致率 100%。这是指定样本的数值对照，不代表所有随机生成逐字逐样本相同。
- 释放 PyTorch decoder 后，其兼容的 `forward_one_step` 仍通过数值检查。
- 双连接同时回复、另一连接开启/关闭、生成中断开后的存活连接均通过实际本地模型测试。
- 实际文字 → LLM → 克隆语音 → LiveTalking → WebRTC 音视频通过，原脸部融合保持。
- 生成的短句、长句经原 SenseVoice 再识别，去标点后的文本相似度均为 100%，没有削波采样。这验证了该样本的可懂度，不能代替主观音色听感评价。
- 8 秒音频 WebRTC 有声跨度约 8.000s，插入静音帧 0；播放中打断后最后有声帧约 199ms。
- 实际录音输入 → VAD → SenseVoice → 本地 LLM → 原克隆语音 → WebSocket 音频回归通过；该轮 3.49s 输入识别耗时约 0.528s。

其余语音可懂度、连续播放和打断回归结果见对应 JSON 与日志；运行中的浏览器控制在本次环境中未启用，因此没有将协议端到端测试表述为重新完成页面点击自动化。

## 复现

```bash
.venv/bin/python scripts/verify-speech-decoder.py
.venv/bin/python scripts/verify-native-speech-decoder.py
.venv/bin/python scripts/diagnose-reply-latency.py
.venv/bin/python scripts/diagnose-reply-latency.py --interrupt-only
.venv/bin/python scripts/verify-session-isolation.py
.venv/bin/python scripts/verify-fast-face-e2e.py
.venv/bin/python scripts/verify-flow-cancellation.py
.venv/bin/python scripts/verify-cloned-speech.py
.venv/bin/python scripts/verify-playback.py
.venv/bin/python scripts/verify-interrupt.py
HEX_VERIFY_TRANSPORT=browser .venv/bin/python scripts/verify-voice.py
```

实际推理和音频测试应串行运行，避免测试之间排队影响性能数据。Flow 取消脚本读取本轮服务器日志 `logs/mac-optimized-final-20261019.log`，需对应的服务进程运行。

证据：`logs/reply-latency-baseline-results.json`、`reply-latency-optimized-results.json`、`reply-latency-interrupt-baseline-results.json`、`reply-latency-interrupt-results.json`、`native-speech-decoder-equivalence.json`、`session-isolation-optimized.log`、`fast-face-e2e-results.json`、`flow-cancellation-results.json`。

默认配置与依赖锁已更新；服务使用 `scripts/start-mac.sh` 启动，`/api/health` 确认预热就绪。重新加载页面后显示新的阶段提示。

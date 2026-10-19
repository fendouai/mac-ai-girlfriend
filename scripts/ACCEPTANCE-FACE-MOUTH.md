# 面部嘴周融合验收 · 2026-10-17

问题定位：原合成使用固定的大椭圆，未按两个人物各自的嘴唇位置和倾角对齐；生成图覆盖鼻翼、脸颊和下巴，256px 网络输出与高分辨率原图之间会出现清晰度、肤色与轮廓变化。说话开始和结束直接切换，也会加重跳变。

本次修改保留 Wav2Lip、原有音频时间线和自然眨眼素材。每个人物的嘴部位置来自离线测量的 478 个关键点；运行时只读 JSON，不加载关键点模型。唇部保留模型运动，外围分频融合保留原图皮肤细节；鼻翼上方、眼睛和下巴轮廓不被嘴部区域替换。肤色修正取嘴周皮肤并单独做时间平滑，不对快速口型做帧平均。开口/收口做最多两帧的局部过渡，打断通过音频 epoch 立即清除历史嘴部状态。

同一段真实参考语音、同一批 Wav2Lip256 输出，旧/新方法各比较 80 帧：

| 人物 | 边缘带相对原图的平均变化（旧 → 新，0–255 像素值） | 新处理平均耗时 | 唇部帧间变化 |
|---|---|---|---|
| 原人物 | 5.789 → 0.438 | 3.28ms | 3.758 |
| 甜美人物 | 5.193 → 0.539 | 4.48ms | 3.677 |

边缘带变化用于判断原图细节保留，不能解释为主观自然度提高了某个百分比。唇部帧间变化与实际对比视频一起确认口型没有冻结。两套人物的嘴部区域之外逐像素不变，包括闭眼帧。

实际 WebRTC 说话测试：原人物解码约 24.55fps、鼻部相对原图 MAE 2.259；甜美人物约 24.08fps、鼻部 MAE 2.563。数据包含连接启动；服务器稳定输出约 25fps。两者均收到非静音音频和真实嘴部运动。

播放回归：8 秒测试音频实际有声跨度约 7.966 秒，插入静音帧 0；打断后最后有声帧约 240ms。新融合没有增加音频队列或改变采样率。

可复现命令：

```bash
.venv/bin/python scripts/verify-mouth-compositor.py
.venv/bin/python scripts/compare-mouth-compositing.py
.venv/bin/python scripts/verify-face-speaking.py
.venv/bin/python scripts/verify-playback.py
.venv/bin/python scripts/verify-interrupt.py
```

原人物/甜美人物新旧对比视频：`logs/hex_clean_original-mouth-comparison.mp4`、`logs/hex_clean_sweet-mouth-comparison.mp4`，均为左旧右新，使用同一音频。数据见 `mouth-comparison-results.json`、`face-speaking-e2e.log`、`mouth-playback-regression.log`、`mouth-interrupt-regression.log`。

本次优化针对贴合与过渡，未把 Wav2Lip 替换为更高精度的面部生成模型；大幅口型、牙齿细节和表情联动仍受原模型能力限制。

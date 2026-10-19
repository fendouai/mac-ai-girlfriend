# 短句语音提示词与分轮展开 · 2026-10-19

## 当前行为

默认先直接回应一小段，通常 10～24 字，最多两句、40 字。安慰不连续劝说；笑话优先完整的短问答，避免长故事。需要更多内容时，用户说或输入“继续”，由下一轮承接上文补充新内容。

这是按对话轮次展开，不是后台自动连发多段，也没有把完整 WAV 播放改成可能欠缓冲的逐句音频拼接。

## 实现

- `persona.md`：短句人设与安慰、问候、短笑话示例。
- `config.mac.yaml`：`max_tokens: 64`、`max_reply_chars: 40`、`max_reply_sentences: 2`、`temperature: 0.65`、`top_p: 0.85`。
- `HexOrchestrator._effective_persona()`：在网页自定义/缓存人设后附加当前语音规则及少量短回答示例；重连时替换自己的旧后缀，不重复追加，也不清除用户的自定义人设。
- `LlamaCppLLM.generate()`：在收到 SSE token 时检查句子和字符预算，提前返回并关闭流，随后只合成选定的短文本；不等待整篇长文生成后再裁掉。默认预算为 0 的其他配置维持原行为。
- 正常情况下通过提示词主动写短。超预算时在邻近的句子或分句边界收尾；模型忽略规则、没有可用边界时才使用字符上限兜底。该保护不能保证所有复杂请求都保留完整含义，较长内容应通过“继续”展开。

## 验证

`verify-reply-budget.py` 检查短句保留、禁用预算、长分句边界、旧人设后缀去重；模拟 HTTP 流仅消费前两句，没有继续读取第三句。

`verify-short-replies.py` 通过真实 WebSocket、当前本地 LLM 和原克隆 TTS 验证问候、安慰、笑话、详细问题和“继续”。它特意模拟已保存的旧版偏长人设，检查各轮不超过 40 字和两句，且存在真实音频、“继续”没有原样重复上轮。文本是否有趣、表达是否自然还需实际观察，字符上限本身不是质量评分。

第一轮实测曾出现被预算截断的故事式笑话，随后加强完整短问答示例并降低采样发散度。最终结果保存在 `logs/short-replies-results.json` 和 `logs/short-replies-final-e2e.log`；不将第一轮长度测试通过等同于语义质量通过。

```bash
.venv/bin/python scripts/verify-reply-budget.py
.venv/bin/python scripts/verify-short-replies.py
```

服务使用新的 `config.mac.yaml` 重新启动；用户刷新网页并重新开始对话后使用最新版本。旧网页人设也会受服务端规则约束。

## 同轮文档与杂音工作

- Mac 说明已成为 `README.md` 主入口，改写前文档完整保存到 `README_ORIGINAL.md`。归档 SHA256：`d7330483766f58cf3cdaa7f1a41de8d28229f3d2c6ac2aaf9e54b84a5aa276ea`。
- 背景声诊断见 [DIAGNOSIS-NOISE.md](DIAGNOSIS-NOISE.md)。短回复策略减少生成等待，不代表噪声门、回声抑制或 VAD 已进一步优化。

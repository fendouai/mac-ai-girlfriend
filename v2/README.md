# Mac AI Girlfriend v2 · DeepSeek Harness 版

v2 是独立目录版本，和仓库根目录的 v1 分开运行。v2 拥有自己的 `src/`、`web/`、`config.mac.yaml`、`data/`、`persona.md` 和测试；复用根目录的 Python 环境、模型权重和 LiveTalking/CosyVoice 依赖。

- v1：仓库根目录，稳定版本。
- v2：本目录，非闲聊任务交给 DeepSeek Harness。
- 设计细节：[docs/V2-HARNESS.md](docs/V2-HARNESS.md)

## 特性

- 本地陪聊继续使用 LM Studio + CosyVoice2；问候、情绪和角色扮演不离开本地。
- 其他任务通过 `dsh --profile headless --json` 交给 DeepSeek Harness。
- 进度显示在页面；完整结果写入“对话记录”；本地模型把结果压缩成一句人声播报。
- 支持 Harness 会话续接、超时、取消，以及缺少凭据时的本地回退。
- v2 默认端口 `7861`，可以和 v1 的 `7860` 同时打开（但共用 `8010` 数字人，建议一次只跑一个）。

## 目录

```text
v2/
  src/                    v2 后端（含 harness.py / harness_router.py）
  web/                    v2 前端（含状态条和 Harness 结果卡片）
  config.mac.yaml         v2 配置（端口 7861，模型路径指向 ../models）
  data/                   参考音色与人物素材
  persona.md              v2 人设
  scripts/start-mac.sh    启动 v2 数字人与网页
  scripts/install-harness.sh  安装固定版本 dsh CLI
  tests/                  路由、桥接与编排测试
  docs/V2-HARNESS.md      设计、权限和路线
```

## 安装与启动

```bash
# 1. 安装根环境、模型和人物素材（首次）
cd v2
./install.sh

# 2. 安装 DeepSeek Harness CLI（本地 .harness-cli/）
./scripts/install-harness.sh

# 3. 配置模型凭据
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY

# 4. 启动 LM Studio 的 8200 API 并加载模型
lms server start --port 8200 --bind 127.0.0.1
lms load dolphin3.0-llama3.1-8b --gpu max --context-length 4096 \
  --identifier dolphin3.0-llama3.1-8b --yes

# 5. 启动 v2
./scripts/start-mac.sh
```

打开 <http://localhost:7861>。健康检查：

```bash
curl -fsS http://127.0.0.1:7861/api/health
```

没有 `DEEPSEEK_API_KEY` 时，非闲聊任务会显示凭据错误并回退本地模型，不会中断语音链路。

## 安全边界

`config.mac.yaml` 当前按 v2.0 的产品选择设置：

```yaml
harness:
  full_access: true
  router:
    mode: auto
```

这会把 `DSH_PERMISSION_MODE` 设为 `danger-full-access`，并且不做逐次命令审批。工作区只是默认 cwd，不是硬边界。语音误识别、网页提示注入或误触发都可能执行任意命令。日常使用建议改成 `full_access: false`，或等 v2.1 接入 ACP 的权限确认。

## 测试

```bash
# 在仓库根目录执行，使用根 .venv
.venv/bin/python -m pytest -q v2/tests/test_harness.py
```

已覆盖：路由、headless 成功/失败/超时/取消、缺命令、缺凭据回退、编排事件。真实 Harness 任务还需要 `.env` 中的 key。

## 与 v1 的关系

- v1 的 README 和代码在仓库根目录，不会被 v2 覆盖。
- v2 复用根目录的 `.venv`、`models/`、`third_party/`；删除或移动这些目录会同时影响两版。
- v2 自己的 `data/` 和 `web/` 是独立副本；修改 v2 不会影响 v1 的页面。
- v2 仍处于开发阶段：真实 key E2E、ACP 权限确认、独立任务卡片尚未完成。

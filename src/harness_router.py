# -*- coding: utf-8 -*-
# =============================================================================
#  Hex AI Girlfriend — v2 task router
#  Copyright (C) 2026 Hex-电脑课堂
#  SPDX-License-Identifier: GPL-3.0-or-later
# =============================================================================
"""Decide whether a turn stays with the local persona or goes to DeepSeek Harness.

The v2 product decision is "all non-chitchat goes to Harness".  A small local
model is good at social chat but unreliable at strict tool-call JSON, so this
router uses explicit task hints plus a conservative social allowlist:

* task hints ("帮我", "查", "写", "代码", "运行", ...) -> Harness
* clearly social / emotional / role-play turns -> local persona
* everything else -> Harness (the default bias)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


# Social turns.  These are intentionally broader than exact greetings: voice
# transcripts rarely carry punctuation, and "你好呀" / "在干嘛呢" should not
# wake a full coding agent.
_SOCIAL_PATTERNS = [
    r"^(你好|您好|嗨|哈喽|hi|hello|hey|在吗|在不在|在干嘛|在干什么|干嘛呢|"
    r"吃了吗|吃饭了吗|睡了吗|早上好|早安|中午好|下午好|晚上好|晚安|"
    r"我回来了|我走了|拜拜|再见)(呀|啊|啦|哦|呢|嘛|哈)*[！!。,.，~～\s]*$",
    r"^(嗯|哦|噢|好|好吧|好呀|好哒|行|可以|没事|知道了|收到|谢谢|谢谢你|"
    r"辛苦了|哈哈|哈哈哈|呵呵|嘻嘻|诶|欸|对|是的|不是)(呀|啊|啦|哦|呢|嘛)*[！!。,.，~～\s]*$",
    r"^(我)?(今天|现在|最近)?(好累|累了|困了|好困|难过|不开心|有点烦|好烦|"
    r"委屈|孤独|害怕|无聊|开心|高兴|心情不好|心情不错|想你|想你了|爱你|喜欢你)"
    r"[啊呀啦哦呢嘛]*[！!。,.，~～\s]*$",
    r"^(抱抱|亲亲|贴贴|摸摸|陪我|哄我|撒娇|夸夸我|夸我一句|安慰我|哄哄我)"
    r"[呀啊啦哦呢嘛]*[！!。,.，~～\s]*$",
    r"^(你是谁|你叫什么|你几岁|你多大|你会什么|你会做什么|介绍一下你自己|介绍下你自己)"
    r"[呀啊呢]*[？?！!。,.，~～\s]*$",
    r"^(讲个笑话|讲一个笑话|说个笑话|唱首歌|唱一个|给我讲个笑话)"
    r"[呀啊吧呢]*[！!。,.，~～\s]*$",
    r"^(你|您)?(喜欢什么|喜欢吃什么|喜欢玩什么|平时做什么|有什么爱好)"
    r"[呀啊呢]*[？?！!。,.，~～\s]*$",
]

# Broad social cues for short voice transcripts that do not match a full
# greeting pattern ("我有点难过", "我饿了", "陪我聊会儿").
_SOCIAL_CUES = re.compile(
    r"(累|困|难过|开心|烦|委屈|孤独|害怕|无聊|想你|想我|爱我|想什么|爱你|喜欢|抱抱|亲亲|贴贴|"
    r"陪我|哄我|撒娇|夸|笑话|唱歌|晚安|早安|你好|在吗|干嘛|吃了吗|睡了吗|"
    r"回来了|谢谢|哈哈|么么|饿了|睡不着|过得怎么样|叫什么名字|多大了|在不在)",
    re.IGNORECASE,
)

_CANCEL_PATTERNS = [
    r"^(算了|停|停下|停止|取消|别做了|不用了|先停一下|暂停)[！!。,.，~～\s]*$",
]

_CONTINUE_PATTERNS = [
    r"^(继续|接着|接着说|继续说|详细说说|展开说说|然后呢)[！!。,.，~～\s]*$",
]

# A task keyword overrides the social allowlist.  This prevents "帮我" or
# "查一下" from being mistaken for chitchat just because the sentence is short.
_TASK_HINTS = re.compile(
    r"(帮|查|搜|找|写|改|修|运行|执行|安装|下载|分析|总结|翻译|生成|做|建|"
    r"代码|文件|项目|目录|仓库|测试|部署|提交|git|命令|脚本|网页|链接|资料|"
    r"天气|新闻|价格|股价|股票|文档|表格|图片|视频|邮件|日程|提醒|搜索|联网|"
    r"推荐|对比|比较|整理|检查|排查|调试|优化|重构|review|harness|agent|深度|任务)",
    re.IGNORECASE,
)


@dataclass
class RouteDecision:
    route: str  # "chat" | "harness" | "cancel" | "continue"
    reason: str = ""
    task: str = ""


class HarnessRouter:
    def __init__(self, cfg: dict[str, Any]):
        hc = cfg.get("harness", {}) if isinstance(cfg, dict) else {}
        router = hc.get("router", {}) if isinstance(hc.get("router", {}), dict) else {}
        self.mode = str(router.get("mode", "auto")).lower()
        self.confirm = bool(router.get("confirm", False))

    @staticmethod
    def _normalize(text: str) -> str:
        return (text or "").strip()

    def is_cancel(self, text: str) -> bool:
        value = self._normalize(text)
        return any(re.search(pattern, value, re.IGNORECASE) for pattern in _CANCEL_PATTERNS)

    def is_continue(self, text: str) -> bool:
        value = self._normalize(text)
        return any(re.search(pattern, value, re.IGNORECASE) for pattern in _CONTINUE_PATTERNS)

    def is_social(self, text: str) -> bool:
        value = self._normalize(text)
        if not value:
            return True
        if _TASK_HINTS.search(value):
            return False
        if any(re.search(pattern, value, re.IGNORECASE) for pattern in _SOCIAL_PATTERNS):
            return True
        return len(value) <= 30 and bool(_SOCIAL_CUES.search(value))

    def decide(self, text: str, *, has_session: bool = False) -> RouteDecision:
        value = self._normalize(text)
        if not value:
            return RouteDecision("chat", "empty")
        if self.is_cancel(value):
            return RouteDecision("cancel", "cancel phrase")
        if self.is_continue(value):
            if has_session:
                return RouteDecision("continue", "continue phrase", "继续")
            return RouteDecision("chat", "continue without task")
        if self.mode == "off":
            return RouteDecision("chat", "router off")
        if self.mode == "explicit":
            if re.search(r"(harness|agent|深度处理|调用\s*harness)", value, re.IGNORECASE):
                return RouteDecision("harness", "explicit trigger", value)
            return RouteDecision("chat", "explicit mode")
        # auto: task hints and anything substantial go to Harness; only clearly
        # social turns stay local.
        if self.is_social(value):
            return RouteDecision("chat", "social")
        return RouteDecision("harness", "non-chitchat", value)

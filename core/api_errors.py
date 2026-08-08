"""上游接口报错的可读化。

翻译和图片反推走的都是第三方 OpenAI 兼容接口。这些接口把「内容被审核拦下」
「Key 不对」「余额不足」一律塞进 error.message 里返回，原样弹给用户就是一串
英文报文，看不出下一步该做什么。

这里只做一件事：认出几类最常见的原因，换成一句能照着做的中文。认不出来的
照旧带上原文——那时候原文是用户唯一的线索，藏起来只会更难查。
"""

from typing import Tuple
import re

_RAW_LIMIT = 200

# (给用户看的原因, 命中任一即判定为该原因的关键词)
# 顺序有意义：审核放最前，它的报文里常常也带着 "policy"、"blocked" 之外的词。
_SIGNATURES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    (
        "上游服务器暂时不可用。Cloudflare 没有收到完整响应，请稍后重试或检查接口提供商的源站配置",
        (
            "cloudflare",
            "origin web server",
            "invalid or incomplete response",
            "bad gateway",
            "gateway time-out",
            "error 520",
            "error 521",
            "error 522",
            "error 523",
            "error 524",
        ),
    ),
    (
        "内容没通过服务商的审核。换个说法、去掉敏感词或换张图再试",
        (
            "flagged",
            "moderation",
            "content policy",
            "content_policy",
            "content_filter",
            "usage policy",
            "prohibited",
            "inappropriate",
            "data_inspection",
            "risk_control",
            "sensitive",
            "safety",
            "censor",
            "审核",
            "违规",
            "敏感",
            "内容政策",
            "合规",
        ),
    ),
    (
        "服务商拒绝了鉴权。检查提供商的 API Key 是否填对、是否过期",
        (
            "invalid api key",
            "invalid_api_key",
            "incorrect api key",
            "unauthorized",
            "authentication",
            "permission denied",
            "无效的令牌",
            "令牌无效",
            "鉴权",
        ),
    ),
    (
        "服务商额度不足或触发了限流。等一会儿再试，或检查账户余额",
        (
            "quota",
            "insufficient",
            "billing",
            "rate limit",
            "rate_limit",
            "too many requests",
            "余额",
            "配额",
            "限流",
            "欠费",
        ),
    ),
    (
        "服务商没有这个模型。到提供商配置里换一个模型",
        (
            "model_not_found",
            "does not exist",
            "no such model",
            "unknown model",
            "unsupported model",
            "模型不存在",
        ),
    ),
)


def _clip(text: str) -> str:
    text = " ".join((text or "").split())

    if len(text) <= _RAW_LIMIT:
        return text

    return f"{text[:_RAW_LIMIT]}…"


# 报错原文和调试流水都可能带着 Key：Gemini 把 key 放在 URL 查询串里，
# aiohttp 的异常消息又常常把整条 URL 带上，一路 logger 打出去就落到日志里了。
_SECRET_PATTERNS: Tuple[Tuple["re.Pattern[str]", str], ...] = (
    (re.compile(r"([?&](?:key|api_?key|access_token|token|auth)=)[^&\s\"']+", re.I), r"\1***"),
    (re.compile(r"(Bearer\s+)[\w.\-]{8,}", re.I), r"\1***"),
    (
        re.compile(
            r"([\"']?(?:api_?key|access_token|authorization)[\"']?\s*[:=]\s*[\"']?)[\w.\-]{8,}",
            re.I,
        ),
        r"\1***",
    ),
    (re.compile(r"\bsk-[\w\-]{8,}"), "sk-***"),
)


def mask_secrets(text: str) -> str:
    """把文本里看着像 API Key 的片段换成 ***。

    宁可多打码：这些文本要么给用户看，要么进日志，漏一个 Key 的代价
    远大于把一串无关字符挡掉。
    """
    masked = text or ""

    for pattern, replacement in _SECRET_PATTERNS:
        masked = pattern.sub(replacement, masked)

    return masked


def describe_api_error(raw: str, subject: str, verbose: bool = False) -> str:
    """把上游接口的原始报错换成一句能照着做的中文。

    subject 形如「提示词翻译」「图片反推」，直接拼在句首。
    verbose 为调试模式：认出原因时也把原始报文附在后面。
    """
    text = mask_secrets((raw or "").strip())
    lowered = text.lower()

    for reason, keywords in _SIGNATURES:
        if any(keyword in lowered for keyword in keywords):
            message = f"{subject}失败：{reason}"

            if verbose and text:
                return f"{message}（原始报错：{_clip(text)}）"

            return message

    # 认不出来的原因，原文就是唯一线索
    return f"{subject}失败：{_clip(text) or '接口没有返回错误信息'}"

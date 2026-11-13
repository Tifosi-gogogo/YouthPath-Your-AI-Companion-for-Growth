import json
import re

from app.models import AIResult, AppError


def _invalid() -> AppError:
    return AppError("invalid_result", "回复格式异常，请重试。")


def _strings(value, limit: int, warnings: list[str], field: str) -> list[str]:
    if not isinstance(value, list):
        warnings.append(f"{field}_invalid")
        return []
    result = []
    for item in value:
        if not isinstance(item, str) or not item.strip() or len(item.strip()) > limit:
            warnings.append(f"{field}_item_ignored")
            continue
        item = item.strip()
        if item not in result:
            result.append(item)
    if len(result) > 3:
        warnings.append(f"{field}_limited")
    return result[:3]


def parse_response(content: str) -> AIResult:
    """mock / 网络回复共用的数据边界；异常 JSON 不直接泄漏到气泡。"""
    if not isinstance(content, str) or not content.strip():
        raise _invalid()
    if len(content) > 65536:
        raise AppError("reply_too_long", "回复长度异常，请重试。")
    text = content.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    warnings = []
    try:
        def unique_fields(pairs):
            obj = {}
            for key, value in pairs:
                if key in obj:
                    raise ValueError("duplicate field")
                obj[key] = value
            return obj

        data = json.loads(text, object_pairs_hook=unique_fields)
    except (ValueError, RecursionError):
        if text.startswith(("{", "[", "```")) or fenced:
            raise _invalid() from None
        if len(text) > 3000:
            raise AppError("reply_too_long", "回复长度异常，请重试。")
        return AIResult(text, risk_level="unknown", warnings=("plain_text_fallback", "risk_unknown"))
    if not isinstance(data, dict):
        raise _invalid()
    reply = data.get("reply")
    if not isinstance(reply, str) or not reply.strip():
        raise _invalid()
    reply = reply.strip()
    if len(reply) > 3000:
        raise AppError("reply_too_long", "回复长度异常，请重试。")
    tags = _strings(data.get("emotion_tags", []), 8, warnings, "emotion_tags")
    suggestions = _strings(data.get("action_suggestions", []), 120, warnings, "action_suggestions")
    risk = data.get("risk_level")
    if risk not in ("normal", "elevated", "urgent"):
        risk = "unknown"
        warnings.append("risk_unknown")
    return AIResult(reply, tags, suggestions, risk, tuple(dict.fromkeys(warnings)))

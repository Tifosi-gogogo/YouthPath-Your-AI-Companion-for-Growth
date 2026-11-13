import json
import logging
import time
from dataclasses import dataclass

import requests

from app.models import AppError
from app.services.settings_store import APISettings, build_endpoint


HTTP_ERRORS = {
    400: ("request_rejected", "请求被服务商拒绝，请检查模型和接口配置。"),
    401: ("authentication", "API Key 无效，请检查后重试。"),
    402: ("insufficient_balance", "账户额度不足，请检查服务商账户。"),
    403: ("permission", "当前账户没有访问权限，请检查账户或模型权限。"),
    404: ("endpoint_or_model", "接口地址或模型编号无效，请检查设置。"),
    429: ("rate_or_quota", "请求过于频繁或额度不足，请稍后重试。"),
}
MAX_RESPONSE_BYTES = 1_048_576


@dataclass(frozen=True)
class Completion:
    content: str
    http_status: int
    elapsed_ms: int


class LLMClient:
    """Chat Completions 非流式适配器。只能由后台任务或 CLI 调用。"""

    def __init__(self, settings: APISettings, post=None):
        self.settings = settings
        self.post = post or requests.post

    def complete(self, messages: list[dict], request_id: str) -> Completion:
        self.settings.validate()
        started = time.monotonic()
        status = None
        error_code = "none"
        response = None
        try:
            payload = {"model": self.settings.model, "messages": messages, "stream": False}
            # OpenAI 的可选参数不强加给其他兼容服务；禁止保存为可检索 completion。
            if build_endpoint(self.settings.api_base_url).startswith("https://api.openai.com/"):
                payload.update(store=False, response_format={"type": "json_object"})
            response = self.post(
                build_endpoint(self.settings.api_base_url),
                headers={"Authorization": f"Bearer {self.settings.api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=(self.settings.connect_timeout_seconds, self.settings.read_timeout_seconds),
                allow_redirects=False,
                stream=True,
            )
            status = response.status_code
            if status != 200:
                code, message = HTTP_ERRORS.get(status, (
                    "service_unavailable" if status >= 500 else "http_error",
                    "AI 服务暂时不可用。" if status >= 500 else "AI 服务请求失败，请检查接口设置。"))
                raise AppError(code, message, status)
            try:
                body = bytearray()
                for chunk in response.iter_content(chunk_size=1024):
                    if time.monotonic() - started > self.settings.request_deadline_seconds:
                        raise AppError("timeout", "本次等待超时，可以稍后重试。")
                    if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise AppError("response_too_large", "服务返回的数据过大，请检查接口或重试。")
                    body.extend(chunk)
                envelope = json.loads(body)
                content = envelope["choices"][0]["message"]["content"]
            except (ValueError, KeyError, IndexError, TypeError, RecursionError):
                raise AppError("invalid_envelope", "回复格式异常，请重试。", status) from None
            if not isinstance(content, str) or not content.strip():
                raise AppError("empty_content", "回复格式异常，请重试。", status)
            return Completion(content, status, round((time.monotonic() - started) * 1000))
        except requests.Timeout:
            error_code = "timeout"
            raise AppError("timeout", "本次等待超时，可以稍后重试。") from None
        except requests.RequestException:
            error_code = "connection"
            raise AppError("connection", "暂时无法连接 AI 服务，请检查网络。") from None
        except AppError as error:
            error_code = error.code
            raise
        finally:
            if response is not None and hasattr(response, "close"):
                response.close()
            logging.getLogger("qingyu").info(
                "request=%s model=%s elapsed_ms=%s http_status=%s error=%s",
                request_id, self.settings.model, round((time.monotonic() - started) * 1000), status, error_code)

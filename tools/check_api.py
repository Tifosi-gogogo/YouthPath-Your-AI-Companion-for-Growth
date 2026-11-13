"""第一天最小 API 验证。仅回显脱敏元数据，不输出请求或模型正文。"""
import argparse
import getpass
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from app.models import AppError
from app.services.llm_client import LLMClient
from app.services.settings_store import APISettings, build_endpoint as validated_endpoint


def build_endpoint(base_url: str) -> str:
    try:
        return validated_endpoint(base_url)
    except AppError as error:
        raise ValueError(error.message) from None


def check_api(base_url: str, model: str, api_key: str) -> dict:
    build_endpoint(base_url)
    settings = APISettings(base_url.strip(), model.strip(), api_key.strip())
    try:
        settings.validate()
    except AppError as error:
        raise ValueError(error.message) from None
    record = {
        "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "request_id": str(uuid4()), "api_base_url": base_url.rstrip("/"),
        "model": model.strip(), "success": False,
    }
    started = time.monotonic()
    try:
        completion = LLMClient(settings).complete([
                {"role": "system", "content": "You are a helpful assistant. Reply with a JSON object containing a greeting in the reply field."},
                {"role": "user", "content": "Reply with a short greeting in Chinese."},
            ], record["request_id"])
        record.update(success=True, http_status=completion.http_status,
                      response_chars=len(completion.content), elapsed_ms=completion.elapsed_ms)
    except AppError as error:
        record["error_type"] = error.code
        if error.http_status is not None:
            record["http_status"] = error.http_status
    record["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description="会产生一次真实 API 调用；消息不进入会话。")
    parser.add_argument("--base-url", default=os.getenv("QINGYU_API_BASE_URL", "https://api.deepseek.com"))
    parser.add_argument("--model", default=os.getenv("QINGYU_MODEL", "deepseek-flash"))
    parser.add_argument("--prompt-key", action="store_true", help="使用隐藏输入读取密钥，不写入文件")
    parser.add_argument("--report", type=Path, help="可选脱敏验证记录路径")
    args = parser.parse_args()
    key = os.getenv("QINGYU_API_KEY", "")
    if not key and args.prompt_key:
        key = getpass.getpass("API Key（隐藏输入，不保存）: ")
    if not key:
        print("未配置 QINGYU_API_KEY。未发起 API 调用；可使用 --prompt-key 安全输入。")
        return 2
    try:
        record = check_api(args.base_url, args.model, key)
    except ValueError as error:
        print(str(error))
        return 2
    rendered = json.dumps(record, ensure_ascii=False, indent=2)
    print(rendered)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    return 0 if record["success"] else 1


if __name__ == "__main__":
    sys.exit(main())

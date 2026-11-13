import json
import logging
import os
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from urllib.parse import urlsplit

from app.models import AppError
from app.utils.paths import load_json, user_data_path


def build_endpoint(base_url: str) -> str:
    base = base_url.strip().rstrip("/")
    try:
        parts = urlsplit(base)
        _ = parts.port
    except ValueError:
        raise AppError("configuration", "API 根地址格式不正确。") from None
    if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
            or any(c.isspace() for c in base) or "\\" in base):
        raise AppError("configuration", "API 根地址必须是无内嵌凭据的 HTTPS 地址。")
    if parts.query or parts.fragment or parts.path.endswith("/chat/completions"):
        raise AppError("configuration", "请填写 API 根地址，不要包含完整请求路径、查询参数或片段。")
    return base + "/chat/completions"


@dataclass(frozen=True)
class APISettings:
    api_base_url: str = ""
    model: str = ""
    api_key: str = field(default="", repr=False)
    connect_timeout_seconds: int = 5
    read_timeout_seconds: int = 40
    request_deadline_seconds: int = 50

    def validate(self, require_key: bool = True) -> None:
        for value in (self.connect_timeout_seconds, self.read_timeout_seconds, self.request_deadline_seconds):
            if type(value) is not int or not 1 <= value <= 120:
                raise AppError("configuration", "请求超时设置必须是 1–120 秒的整数。")
        if not self.api_base_url.strip() and not self.model.strip() and not require_key:
            return
        if not self.api_base_url.strip() or not self.model.strip():
            raise AppError("configuration", "请填写 API 根地址和模型编号。")
        build_endpoint(self.api_base_url)
        if not self.model.strip() or len(self.model) > 200 or any(c.isspace() for c in self.model):
            raise AppError("configuration", "请填写有效的模型编号，不要包含空白字符。")
        if require_key and not self.api_key.strip():
            raise AppError("configuration", "请填写 API Key 或配置 QINGYU_API_KEY。")
        if self.api_key and any(c.isspace() for c in self.api_key):
            raise AppError("configuration", "API Key 不应包含空白字符。")


class SettingsStore:
    def __init__(self, path: Path | None = None):
        self.path = path or user_data_path() / "settings.json"
        self.load_warning = ""
        self.current = APISettings()
        self.load()

    def load(self) -> APISettings:
        defaults = load_json("config/default_settings.json")
        allowed = ("api_base_url", "model", "connect_timeout_seconds", "read_timeout_seconds", "request_deadline_seconds")
        values = {key: defaults[key] for key in allowed}
        if self.path.exists():
            try:
                if self.path.stat().st_size > 65536:
                    raise ValueError
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError
                candidate = {**values, **{key: data[key] for key in allowed if key in data}}
                if not all(isinstance(candidate[key], str) for key in ("api_base_url", "model")):
                    raise ValueError
                APISettings(**candidate).validate(require_key=False)
                values = candidate
            except (OSError, ValueError, RecursionError, AppError):
                self.load_warning = "接口设置无法读取，已使用默认值；原文件已保留。"
                logging.getLogger("qingyu").warning("settings_load=failed")
        values["api_base_url"] = os.getenv("QINGYU_API_BASE_URL", values["api_base_url"]).strip()
        values["model"] = os.getenv("QINGYU_MODEL", values["model"]).strip()
        self.current = APISettings(**values, api_key=os.getenv("QINGYU_API_KEY", "").strip())
        return self.current

    def save(self, settings: APISettings) -> None:
        settings = replace(settings, api_base_url=settings.api_base_url.strip().rstrip("/"),
                           model=settings.model.strip(), api_key=settings.api_key.strip())
        settings.validate(require_key=False)
        payload = {key: getattr(settings, key) for key in (
            "api_base_url", "model", "connect_timeout_seconds", "read_timeout_seconds", "request_deadline_seconds")}
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix="settings-", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except OSError:
            raise AppError("settings_save", "设置未保存，请检查用户数据目录的写入权限。") from None
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    logging.getLogger("qingyu").warning("settings_temp_cleanup=failed")
        self.current = settings
        self.load_warning = ""

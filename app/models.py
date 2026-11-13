from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from uuid import uuid4


def new_id() -> str:
    return str(uuid4())


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class AIResult:
    reply: str
    emotion_tags: list[str] = field(default_factory=list)
    action_suggestions: list[str] = field(default_factory=list)
    risk_level: str = "unknown"
    warnings: tuple[str, ...] = ()


class RequestState(str, Enum):
    IDLE = "idle"
    SENDING = "sending"
    FINISHING = "finishing"
    STOPPING = "stopping"


class AppError(Exception):
    """只携带受控用户提示和错误代码，不能携带服务器原始正文。"""

    def __init__(self, code: str, message: str, http_status: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


@dataclass
class Message:
    role: str
    text: str
    message_id: str = field(default_factory=new_id)
    created_at: str = field(default_factory=now_iso)
    status: str = "pending"
    result: AIResult | None = None
    source: str = "mock"
    demo_case_id: str | None = None
    safety_support: bool = False


@dataclass(frozen=True)
class RequestContext:
    session_id: str
    user_message_id: str
    request_id: str = field(default_factory=new_id)


@dataclass
class Session:
    session_id: str = field(default_factory=new_id)
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    character_version: str = ""
    mode: str = "demo"
    demo_case_id: str | None = None
    messages: list[Message] = field(default_factory=list)

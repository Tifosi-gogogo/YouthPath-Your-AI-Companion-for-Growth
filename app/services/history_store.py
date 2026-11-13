import json
import logging
import os
import tempfile
import shutil
from pathlib import Path
from uuid import UUID, uuid4

from app.models import AIResult, AppError, Message, Session, now_iso
from app.services.response_parser import parse_response
from app.utils.paths import user_data_path


def _identity(value) -> str:
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError
        return value
    except (ValueError, AttributeError):
        raise AppError("history_invalid", "记录无法读取，原文件已保留。") from None


def _atomic_json(path: Path, payload: dict):
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix="session-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError:
        raise AppError("history_save", "当前对话尚未保存，请重试保存或手动导出。") from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                logging.getLogger("qingyu").warning("history_temp_cleanup=failed")


def session_payload(session: Session) -> dict:
    messages = []
    for item in session.messages:
        data = {key: getattr(item, key) for key in ("message_id", "role", "text", "created_at", "status",
                                                   "source", "demo_case_id", "safety_support")}
        if item.result:
            data["result"] = {key: getattr(item.result, key) for key in (
                "reply", "emotion_tags", "action_suggestions", "risk_level")}
        messages.append(data)
    return {"schema_version": 1, "session_id": session.session_id, "created_at": session.created_at,
            "updated_at": session.updated_at, "character_version": session.character_version,
            "mode": session.mode, "demo_case_id": session.demo_case_id, "messages": messages}


class HistoryStore:
    def __init__(self, root: Path | None = None):
        self.root = root or user_data_path()
        self.directory = self.root / "sessions"
        self.pointer = self.root / "latest_session.json"

    def save(self, session: Session):
        session.updated_at = now_iso()
        path = self.directory / f"{_identity(session.session_id)}.json"
        _atomic_json(path, session_payload(session))
        _atomic_json(self.pointer, {"session_id": session.session_id})

    def load(self, session_id: str) -> Session:
        path = self.directory / f"{_identity(session_id)}.json"
        try:
            if path.stat().st_size > 10_000_000:
                raise ValueError
            data = json.loads(path.read_text(encoding="utf-8"))
            if (not isinstance(data, dict) or data["schema_version"] != 1 or data["mode"] not in ("demo", "online", "mock")
                    or data["session_id"] != session_id or not isinstance(data["messages"], list)):
                raise ValueError
            _identity(data["session_id"])
            for key in ("created_at", "updated_at", "character_version"):
                if not isinstance(data[key], str) or len(data[key]) > 200:
                    raise ValueError
            case_id = data.get("demo_case_id")
            if case_id is not None and (not isinstance(case_id, str) or len(case_id) > 100):
                raise ValueError
            # 兼容旧版本的案例编号，恢复后保存为通用编号。
            legacy_case_id = case_id
            if case_id == "pv-study":
                case_id = "study-tasks"
            session = Session(session_id=session_id, created_at=data["created_at"], updated_at=data["updated_at"],
                character_version=data["character_version"], mode=data["mode"], demo_case_id=case_id)
            seen = set()
            for row in data["messages"]:
                if not isinstance(row, dict):
                    raise ValueError
                identifier = _identity(row["message_id"])
                if identifier in seen:
                    raise ValueError
                seen.add(identifier)
                if (row["role"] not in ("user", "assistant") or row["status"] not in ("pending", "completed", "failed", "cancelled")
                        or row.get("source") != session.mode or not isinstance(row["text"], str)
                        or not row["text"].strip() or len(row["text"]) > (2000 if row["role"] == "user" else 3000)
                        or not isinstance(row["created_at"], str) or len(row["created_at"]) > 100
                        or type(row.get("safety_support", False)) is not bool
                        or row.get("demo_case_id") != legacy_case_id):
                    raise ValueError
                result = parse_response(json.dumps(row["result"], ensure_ascii=False)) if row.get("result") is not None else None
                if result and result.reply != row["text"]:
                    raise ValueError
                item = Message(row["role"], row["text"], identifier, row["created_at"],
                    "failed" if row["status"] == "pending" else row["status"], result,
                    session.mode, session.demo_case_id, row.get("safety_support", False))
                session.messages.append(item)
            return session
        except (OSError, KeyError, ValueError, TypeError, RecursionError, AppError):
            raise AppError("history_invalid", "记录无法读取，原文件已保留。") from None

    def latest(self) -> Session | None:
        if not self.pointer.exists():
            return None
        try:
            if self.pointer.stat().st_size > 4096:
                raise ValueError
            data = json.loads(self.pointer.read_text(encoding="utf-8"))
            return self.load(data["session_id"])
        except (OSError, ValueError, KeyError, TypeError, RecursionError, AppError):
            try:
                backup = self.root / f"latest_session.invalid-{uuid4()}.json"
                shutil.copyfile(self.pointer, backup)
            except OSError:
                logging.getLogger("qingyu").warning("history_pointer_backup=failed")
            raise AppError("history_invalid", "记录无法读取，已创建新会话；原文件已保留。") from None

    def list_sessions(self) -> tuple[list[Session], int]:
        valid, invalid = [], 0
        if self.directory.exists():
            for path in self.directory.glob("*.json"):
                try:
                    valid.append(self.load(path.stem))
                except AppError:
                    invalid += 1
        valid.sort(key=lambda session: session.updated_at, reverse=True)
        return valid, invalid

    def delete(self, session: Session):
        try:
            (self.directory / f"{_identity(session.session_id)}.json").unlink(missing_ok=True)
            # 只删除当前记录，不触碰导出文件与其他会话。
            self.pointer.unlink(missing_ok=True)
        except OSError:
            raise AppError("history_delete", "当前记录未清空，请检查目录权限后重试。") from None

    @staticmethod
    def export(session: Session, path: Path):
        try:
            if path.suffix.lower() == ".json":
                _atomic_json(path, session_payload(session))
            else:
                mode = {"demo": "离线演示 · 预设案例，非实时 AI 回复", "online": "真实在线会话", "mock": "开发 MOCK"}[session.mode]
                lines = ["青语伴行 — 许青", f"模式：{mode}", f"创建：{session.created_at}", ""]
                for item in session.messages:
                    lines.extend([f"{item.created_at} · {'你' if item.role == 'user' else '许青'} · {item.status}", item.text])
                    if item.result:
                        lines.append("情绪标签：" + " / ".join(item.result.emotion_tags))
                        lines.extend(f"行动建议 {i}：{value}" for i, value in enumerate(item.result.action_suggestions, 1))
                    if item.safety_support:
                        lines.append("本轮附有本地安全支持提示")
                    lines.append("")
                path.write_text("\n".join(lines), encoding="utf-8")
        except OSError:
            raise AppError("history_export", "导出失败，请选择可写目录。") from None

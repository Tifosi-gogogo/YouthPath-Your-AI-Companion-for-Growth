from app.models import AppError, Message
from app.services.character_config import CharacterConfig
from app.utils.paths import resource_path


def build_system_prompt(character: CharacterConfig) -> str:
    template = resource_path("config/system_prompt.txt").read_text(encoding="utf-8")
    return template.format(name=character.name, nickname=character.nickname or character.name,
        traits="、".join(character.traits), communication_style=character.communication_style,
        background=character.background, bio=character.bio, age_description=character.age_description)


def build_messages(character: CharacterConfig, history: list[Message], current: Message,
                   mode: str = "online", max_turns: int = 6, budget: int = 12000) -> list[dict]:
    system = build_system_prompt(character)
    if len(system) + len(current.text) > budget:
        raise AppError("context_budget", "角色规则和当前问题超过上下文预算，请缩短问题；不会截断安全规则。")
    pairs = []
    pending = None
    if mode == "online":
        for item in history:
            if item.message_id == current.message_id:
                break
            if item.source != "online" or item.safety_support or item.status != "completed":
                pending = None
                continue
            if item.role == "user":
                pending = item
            elif item.role == "assistant" and pending is not None:
                pairs.append((pending, item))
                pending = None
    pairs = pairs[-max_turns:] if max_turns > 0 else []
    size = len(system) + len(current.text) + sum(len(u.text) + len(a.text) for u, a in pairs)
    while pairs and size > budget:
        u, a = pairs.pop(0)
        size -= len(u.text) + len(a.text)
    messages = [{"role": "system", "content": system}]
    for user, assistant in pairs:
        messages.extend([{"role": "user", "content": user.text}, {"role": "assistant", "content": assistant.text}])
    messages.append({"role": "user", "content": current.text})
    return messages

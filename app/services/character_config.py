import json
import logging
from dataclasses import dataclass
from pathlib import Path

from app.utils.paths import resource_path


@dataclass(frozen=True)
class CharacterConfig:
    version: str = "0.2-dev"
    name: str = "青语（开发暂名）"
    identity: str = "AI 青年成长陪伴辅导员"
    age_description: str = "角色年龄设定待 A 确认"
    traits: tuple[str, ...] = ("温和", "尊重", "务实")
    bio: str = "一起梳理困扰，从一件小事开始。角色材料待 A 交付。"
    welcome: str = "你好，欢迎来到青语伴行，我们可以一起慢慢梳理最近的困扰。"
    avatar: str = "assets/images/avatar.png"
    portrait: str = "assets/images/character.png"
    disclaimer: str = "成长陪伴工具，不替代专业心理咨询。"
    nickname: str = ""
    background: str = ""
    tagline: str = "一起梳理困扰\n从一件小事开始"
    appearance: str = ""
    communication_style: str = ""
    gender: str = ""
    voice_design: str = ""
    warnings: tuple[str, ...] = ()

    def image_path(self, field: str = "avatar") -> Path | None:
        relative = getattr(self, field)
        root = resource_path("").resolve()
        path = resource_path(relative).resolve()
        if path.is_relative_to(root) and path.is_file():
            return path
        return None


def load_character(path: Path | None = None) -> CharacterConfig:
    default = CharacterConfig()
    warnings = []
    try:
        data = json.loads((path or resource_path("config/character.json")).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError
    except (OSError, ValueError):
        data = {}
        warnings.append("character_config_unavailable")
    values = {}
    for field in ("version", "name", "identity", "age_description", "bio", "welcome", "avatar", "portrait", "disclaimer"):
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            values[field] = getattr(default, field)
            warnings.append(f"{field}_fallback")
        else:
            values[field] = value.strip()
    traits = data.get("traits")
    if isinstance(traits, list) and traits and all(isinstance(t, str) and t.strip() for t in traits):
        values["traits"] = tuple(t.strip() for t in traits)
    else:
        values["traits"] = default.traits
        warnings.append("traits_fallback")
    for field in ("nickname", "background", "tagline", "appearance", "communication_style", "gender", "voice_design"):
        value = data.get(field)
        values[field] = value.strip() if isinstance(value, str) and value.strip() else getattr(default, field)
    character = CharacterConfig(**values)
    for field in ("avatar", "portrait"):
        if character.image_path(field) is None:
            warnings.append(f"{field}_unavailable")
    if warnings:
        logging.getLogger("qingyu").warning("character_load=%s", ",".join(warnings))
    return CharacterConfig(**values, warnings=tuple(warnings))

import json
from dataclasses import dataclass

from app.models import AIResult, AppError
from app.services.response_parser import parse_response
from app.utils.paths import load_json


@dataclass(frozen=True)
class DemoTurn:
    question: str
    result: AIResult


@dataclass(frozen=True)
class DemoCase:
    case_id: str
    title: str
    scene: str
    turns: tuple[DemoTurn, ...]


class DemoService:
    """只匹配用户选择案例中的下一句，不将任意输入伪装成生成结果。"""

    def __init__(self):
        data = load_json("assets/demo_cases.json")
        self.cases = tuple(DemoCase(item["id"], item["title"], item["scene"], tuple(
            DemoTurn(turn["question"], parse_response(json.dumps(turn["result"], ensure_ascii=False)))
            for turn in item["turns"])) for item in data["cases"])

    def get(self, case_id: str) -> DemoCase:
        case = next((case for case in self.cases if case.case_id == case_id), None)
        if case is None:
            raise AppError("demo_case", "演示案例无法读取，请选择其他案例。")
        return case

    def next_turn(self, case_id: str, completed_turns: int) -> DemoTurn | None:
        case = self.get(case_id)
        return case.turns[completed_turns] if completed_turns < len(case.turns) else None

    def result_for(self, case_id: str, completed_turns: int, question: str) -> AIResult:
        turn = self.next_turn(case_id, completed_turns)
        if turn is None or question.strip() != turn.question:
            raise AppError("demo_input", "当前是预设案例演示。请使用本案例的示例问题；自由对话待接入 API。")
        return parse_response(json.dumps({"reply": turn.result.reply,
            "emotion_tags": turn.result.emotion_tags, "action_suggestions": turn.result.action_suggestions,
            "risk_level": turn.result.risk_level}, ensure_ascii=False))

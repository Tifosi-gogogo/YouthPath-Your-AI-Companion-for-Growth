import json
from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from app.controllers.chat_controller import ChatController
from app.models import AIResult, AppError, Message, Session
from app.services.character_config import load_character
from app.services.demo_service import DemoService
from app.services.history_store import HistoryStore, session_payload
from app.services.prompt_builder import build_messages, build_system_prompt
from app.services.safety_service import has_immediate_risk
from app.ui.main_window import MainWindow
from app.ui.history_dialog import HistoryDialog
from app.ui.character_dialog import CharacterDialog
from tests.conftest import spin_until


def controller_for(tmp_path, **kwargs):
    return ChatController(mode="demo", history_store=HistoryStore(tmp_path), **kwargs)


def test_demo_arbitrary_input_is_rejected_and_all_cases_parse(qt_app, tmp_path):
    demo = DemoService()
    assert len(demo.cases) == 6
    for case in demo.cases:
        for index, turn in enumerate(case.turns):
            assert demo.result_for(case.case_id, index, turn.question).reply
    controller = controller_for(tmp_path)
    assert not controller.send("任何自由问题")
    assert not controller.messages and not controller.busy


def test_demo_two_turns_restart_restore_and_no_repeat(qt_app, tmp_path):
    controller = controller_for(tmp_path)
    first = controller.next_demo_question()
    assert controller.send(first)
    assert not controller.send(first)
    spin_until(lambda: not controller.busy)
    second = controller.next_demo_question()
    assert second and second != first
    assert controller.send(second)
    spin_until(lambda: not controller.busy)
    restored = controller_for(tmp_path)
    assert len(restored.messages) == 4
    assert not restored.busy and not restored.next_demo_question()
    assert all(item.source == "demo" for item in restored.messages)
    assert not restored.send(first)


def test_demo_cancel_retry_and_case_change_isolates_results(qt_app, tmp_path):
    controller = controller_for(tmp_path)
    controller.send(controller.next_demo_question())
    old = controller.active
    controller.cancel()
    controller._success(old, AIResult("过期"))
    assert not controller.select_case("career")
    spin_until(lambda: not controller.busy)
    assert controller.retry()
    spin_until(lambda: not controller.busy)
    assert len(controller.messages) == 2
    old_session = controller.session_id
    assert controller.select_case("career")
    assert controller.session_id != old_session and not controller.messages
    assert controller.history_store.load(old_session).demo_case_id == "study-tasks"


def test_pending_restore_is_failed_and_does_not_start_request(qt_app, tmp_path):
    store = HistoryStore(tmp_path)
    session = Session(mode="demo", demo_case_id="study-tasks")
    session.messages.append(Message("user", DemoService().get("study-tasks").turns[0].question,
                                    source="demo", demo_case_id="study-tasks"))
    store.save(session)
    controller = controller_for(tmp_path)
    assert not controller.busy
    assert controller.messages[0].status == "failed"
    assert controller.retry_message_id == session.messages[0].message_id


def test_history_corrupt_preserved_atomic_failure_and_path_rejection(tmp_path, monkeypatch):
    store = HistoryStore(tmp_path)
    session = Session(mode="demo", demo_case_id="study-tasks")
    store.save(session)
    path = store.directory / f"{session.session_id}.json"
    original = path.read_bytes()
    import app.services.history_store as module
    def fail(*args):
        raise OSError("controlled write failure")
    monkeypatch.setattr(module.os, "replace", fail)
    with pytest.raises(AppError):
        store.save(session)
    assert path.read_bytes() == original
    assert not list(store.directory.glob("*.tmp"))
    path.write_text("{bad", encoding="utf-8")
    with pytest.raises(AppError):
        store.latest()
    assert path.read_text(encoding="utf-8") == "{bad"
    assert list(tmp_path.glob("latest_session.invalid-*.json"))
    with pytest.raises(AppError):
        store.load("../outside")


def test_history_clear_keeps_other_session_and_exports_have_mode(qt_app, tmp_path):
    controller = controller_for(tmp_path)
    controller.send(controller.next_demo_question())
    spin_until(lambda: not controller.busy)
    old_id = controller.session_id
    txt = tmp_path / "export.txt"
    exported = tmp_path / "export.json"
    HistoryStore.export(controller.session, txt)
    HistoryStore.export(controller.session, exported)
    assert "非实时 AI 回复" in txt.read_text(encoding="utf-8")
    assert "行动建议" in txt.read_text(encoding="utf-8")
    data = json.loads(exported.read_text(encoding="utf-8"))
    assert data["mode"] == "demo" and data["messages"][1]["result"]["emotion_tags"]
    assert "api_key" not in json.dumps(data)
    controller.new_session()
    current_id = controller.session_id
    assert controller.clear_session()
    assert not (controller.history_store.directory / f"{current_id}.json").exists()
    assert (controller.history_store.directory / f"{old_id}.json").exists()
    assert txt.exists() and exported.exists()


def test_save_failure_retains_memory_and_can_retry(qt_app, tmp_path, monkeypatch):
    controller = controller_for(tmp_path)
    original = controller.history_store.save
    def failure(session):
        raise AppError("history_save", "当前对话尚未保存")
    monkeypatch.setattr(controller.history_store, "save", failure)
    assert controller.send(controller.next_demo_question())
    spin_until(lambda: not controller.busy)
    assert len(controller.messages) == 2 and controller.save_error
    monkeypatch.setattr(controller.history_store, "save", original)
    assert controller.save() and not controller.save_error


def test_prompt_context_only_complete_online_pairs_deduplicates_and_trims():
    character = load_character()
    assert "许青" in build_system_prompt(character)
    history = []
    for i in range(8):
        history.extend([Message("user", f"问题{i}" + "问" * 100, status="completed", source="online"),
                        Message("assistant", f"回复{i}" + "答" * 100, status="completed", source="online")])
    history.extend([Message("user", "失败问题", status="failed", source="online"),
                    Message("assistant", "演示内容", status="completed", source="demo")])
    current = Message("user", "本次问题", source="online")
    messages = build_messages(character, history + [current], current)
    assert len(messages) == 14
    assert sum(row["content"] == "本次问题" for row in messages) == 1
    assert not any(row["content"] in ("失败问题", "演示内容") for row in messages)
    budget = len(build_system_prompt(character)) + len(current.text) + 210
    trimmed = build_messages(character, history, current, budget=budget)
    assert len(trimmed) == 4 and "问题7" in trimmed[1]["content"]
    assert len(build_messages(character, history, current, mode="demo")) == 2
    with pytest.raises(AppError):
        build_messages(character, history, current, budget=10)


def test_failed_save_blocks_switch_and_close_until_export_or_retry(qt_app, tmp_path, monkeypatch):
    controller = controller_for(tmp_path)
    assert controller.send(controller.next_demo_question())
    spin_until(lambda: not controller.busy)
    original = controller.history_store.save
    session_id = controller.session_id
    def failure(session):
        raise AppError("history_save", "当前对话尚未保存")
    monkeypatch.setattr(controller.history_store, "save", failure)
    assert not controller.new_session()
    assert not controller.select_case("career")
    assert controller.session_id == session_id and controller.demo_case_id == "study-tasks"
    assert len(controller.messages) == 2
    window = MainWindow(controller=controller)
    window.show()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.No)
    assert not window.close() and window.isVisible()
    assert not window.closing and window.send.isEnabled()
    HistoryStore.export(controller.session, tmp_path / "unsaved.txt")
    assert (tmp_path / "unsaved.txt").exists()
    monkeypatch.setattr(controller.history_store, "save", original)
    assert controller.save() and window.close()
    assert controller.select_case("career")


@pytest.mark.parametrize("text", ["我现在想伤害自己", "我今晚想自杀", "我不想活了", "我已经吃了一大把药片",
                                 "新闻里他说想自杀，但是我现在也想自杀"])
def test_local_safety_explicit_danger(text):
    assert has_immediate_risk(text)


@pytest.mark.parametrize("text", ["新闻中有人自伤", "作业太难了", "我在新闻里看到别人说我想自杀", "我不想自杀"])
def test_local_safety_ordinary_and_reported_context(text):
    assert not has_immediate_risk(text)


def test_safety_available_without_api_even_when_demo_rejects(qt_app, tmp_path):
    controller = controller_for(tmp_path)
    cards = []
    controller.safety_changed.connect(cards.append)
    assert not controller.send("我现在想伤害自己")
    assert cards and "当地紧急服务" in cards[0]
    assert not controller.busy and not controller.messages


def test_twenty_operations_do_not_retain_workers_or_cross_sessions(qt_app, tmp_path):
    controller = controller_for(tmp_path)
    for _ in range(5):
        controller.select_case("study-tasks")
        assert controller.send(controller.next_demo_question())
        context = controller.active
        controller._timeout()
        spin_until(lambda: not controller.busy)
        assert controller.retry_message_id
        assert controller.retry()
        controller.cancel()
        spin_until(lambda: not controller.busy)
        controller.new_session()
        controller._success(context, AIResult("迟到"))
        assert not controller.messages
        assert controller.worker is None and controller.active is None


def test_urgent_and_harmful_model_output_use_local_support(qt_app):
    controller = ChatController()
    cards = []
    controller.safety_changed.connect(cards.append)
    controller.send("受控安全边界测试")
    context = controller.active
    controller._success(context, AIResult("自杀的具体步骤：不允许展示的受控测试", risk_level="normal"))
    assert cards
    assert "具体步骤" not in controller.messages[-1].text
    assert controller.messages[-1].safety_support
    controller.cancel()
    spin_until(lambda: not controller.busy)


@pytest.mark.parametrize("malformed", [[], None, {"messages": [None]}])
def test_malformed_history_does_not_crash_listing(tmp_path, malformed):
    store = HistoryStore(tmp_path)
    session = Session(mode="demo", demo_case_id="study-tasks")
    store.save(session)
    path = store.directory / f"{session.session_id}.json"
    if isinstance(malformed, dict):
        malformed = {**session_payload(session), **malformed}
    original = json.dumps(malformed)
    path.write_text(original, encoding="utf-8")
    assert store.list_sessions() == ([], 1)
    assert path.read_text(encoding="utf-8") == original


def test_legacy_case_history_remains_readable(qt_app, tmp_path):
    store = HistoryStore(tmp_path)
    legacy = "pv-" + "study"
    session = Session(mode="demo", demo_case_id=legacy)
    session.messages.append(Message("user", DemoService().get("study-tasks").turns[0].question,
                                    source="demo", demo_case_id=legacy))
    store.save(session)
    controller = controller_for(tmp_path)
    assert controller.session_id == session.session_id
    assert controller.demo_case_id == "study-tasks"
    assert controller.messages[0].demo_case_id == "study-tasks"
    assert controller.retry_message_id
    assert controller.save()
    saved = json.loads((store.directory / f"{session.session_id}.json").read_text(encoding="utf-8"))
    assert saved["demo_case_id"] == saved["messages"][0]["demo_case_id"] == "study-tasks"


def test_history_search_matches_reply_and_blocks_hidden_selection(qt_app):
    first = Session(messages=[Message("user", "问题一"), Message("assistant", "先给薄荷浇水")])
    second = Session(messages=[Message("user", "问题二"), Message("assistant", "整理课程笔记")])
    dialog = HistoryDialog([first, second])
    dialog.search.setText("薄荷")
    assert not dialog.items.item(0).isHidden() and dialog.items.item(1).isHidden()
    assert dialog.open_button.isEnabled()
    dialog.search.setText("没有这个词")
    assert not dialog.open_button.isEnabled()
    dialog._open()
    assert dialog.selected_session is None
    dialog.search.clear()
    dialog.items.setCurrentRow(1)
    dialog._open()
    assert dialog.selected_session.session_id == second.session_id


def test_switching_sessions_clears_previous_draft(qt_app, tmp_path):
    window = MainWindow(history_store=HistoryStore(tmp_path), restore=False)
    window.input.setPlainText("上一段对话的草稿")
    window.controller.new_session()
    assert not window.input.toPlainText()
    window.input.setPlainText("另一段草稿")
    window.controller.clear_session()
    assert not window.input.toPlainText()
    window.close()


def test_role_profile_contains_delivered_gender_and_voice(qt_app):
    from PySide6.QtWidgets import QLabel
    character = load_character()
    dialog = CharacterDialog(character)
    text = "\n".join(label.text() for label in dialog.findChildren(QLabel))
    assert character.gender and character.gender in text
    assert "文字音色设计" in character.voice_design and character.voice_design in text
    dialog.close()

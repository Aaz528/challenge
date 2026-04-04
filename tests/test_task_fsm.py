"""Тесты графа переходов задачи (task FSM)."""

from __future__ import annotations

import pytest

from chat_service import (
    TASK_STAGE_DONE,
    TASK_STAGE_EXECUTION,
    TASK_STAGE_PLANNING,
    TASK_STAGE_VALIDATION,
    get_task_fsm_state,
    pause_task_fsm,
    resume_task_fsm,
    transition_task_fsm,
)
from sqlite_chat_storage import SQLiteChatStorage


@pytest.fixture
def chat_branch(tmp_path) -> tuple[SQLiteChatStorage, int]:
    db = tmp_path / "test.db"
    s = SQLiteChatStorage(str(db))
    s.ensure_schema()
    chat_id = s.create_chat(title="t", system_prompt="sys")
    bid = s.get_main_branch_id(chat_id)
    assert bid is not None
    yield s, bid
    s.close()


def test_default_stage_is_planning(chat_branch: tuple[SQLiteChatStorage, int]) -> None:
    storage, bid = chat_branch
    st = get_task_fsm_state(storage, bid)
    assert st.stage == TASK_STAGE_PLANNING


def test_invalid_skip_planning_to_validation(chat_branch: tuple[SQLiteChatStorage, int]) -> None:
    storage, bid = chat_branch
    with pytest.raises(ValueError, match="запрещен"):
        transition_task_fsm(storage, bid, TASK_STAGE_VALIDATION)


def test_invalid_skip_planning_to_done(chat_branch: tuple[SQLiteChatStorage, int]) -> None:
    storage, bid = chat_branch
    with pytest.raises(ValueError, match="запрещен"):
        transition_task_fsm(storage, bid, TASK_STAGE_DONE)


def test_invalid_execution_to_done_skips_validation(chat_branch: tuple[SQLiteChatStorage, int]) -> None:
    storage, bid = chat_branch
    transition_task_fsm(storage, bid, TASK_STAGE_EXECUTION)
    with pytest.raises(ValueError, match="запрещен"):
        transition_task_fsm(storage, bid, TASK_STAGE_DONE)


def test_valid_linear_path(chat_branch: tuple[SQLiteChatStorage, int]) -> None:
    storage, bid = chat_branch
    assert get_task_fsm_state(storage, bid).stage == TASK_STAGE_PLANNING

    transition_task_fsm(storage, bid, TASK_STAGE_EXECUTION)
    assert get_task_fsm_state(storage, bid).stage == TASK_STAGE_EXECUTION

    transition_task_fsm(storage, bid, TASK_STAGE_VALIDATION)
    assert get_task_fsm_state(storage, bid).stage == TASK_STAGE_VALIDATION

    transition_task_fsm(storage, bid, TASK_STAGE_DONE)
    assert get_task_fsm_state(storage, bid).stage == TASK_STAGE_DONE


def test_done_has_no_outgoing_transitions(chat_branch: tuple[SQLiteChatStorage, int]) -> None:
    storage, bid = chat_branch
    transition_task_fsm(storage, bid, TASK_STAGE_EXECUTION)
    transition_task_fsm(storage, bid, TASK_STAGE_VALIDATION)
    transition_task_fsm(storage, bid, TASK_STAGE_DONE)
    with pytest.raises(ValueError, match="запрещен"):
        transition_task_fsm(storage, bid, TASK_STAGE_EXECUTION)


def test_pause_must_not_use_transition(chat_branch: tuple[SQLiteChatStorage, int]) -> None:
    storage, bid = chat_branch
    with pytest.raises(ValueError, match="pause_task_fsm"):
        transition_task_fsm(storage, bid, "paused")


def test_cannot_transition_from_paused_without_resume(chat_branch: tuple[SQLiteChatStorage, int]) -> None:
    storage, bid = chat_branch
    pause_task_fsm(storage, bid, "stop")
    assert get_task_fsm_state(storage, bid).stage == "paused"
    with pytest.raises(ValueError, match="resume_task_fsm"):
        transition_task_fsm(storage, bid, TASK_STAGE_EXECUTION)


def test_resume_restores_previous_stage(chat_branch: tuple[SQLiteChatStorage, int]) -> None:
    storage, bid = chat_branch
    transition_task_fsm(storage, bid, TASK_STAGE_EXECUTION)
    pause_task_fsm(storage, bid, "wait")
    assert get_task_fsm_state(storage, bid).stage == "paused"
    resume_task_fsm(storage, bid)
    assert get_task_fsm_state(storage, bid).stage == TASK_STAGE_EXECUTION

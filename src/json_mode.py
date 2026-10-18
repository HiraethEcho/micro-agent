"""通过 stdin/stdout JSON Lines 与外部程序交互。"""

import json
from collections import deque
from typing import Callable, TextIO
from uuid import uuid4

from agent import MicroAgent

EventWriter = Callable[[dict], None]


def run_json_protocol(
    agent: MicroAgent,
    input_stream: TextIO,
    write_event: EventWriter,
    *,
    initial_prompt: str | None = None,
) -> int:
    """读取 prompt 和审批输入，并按发生顺序输出 JSON 事件。"""
    lines = iter(input_stream)
    queued_prompts: deque[dict] = deque()
    had_error = False

    def emit(
        event: dict, request_id: str | None = None, turn_id: str | None = None
    ) -> None:
        """补充关联 ID，方便调用方关联一轮中的模型和工具事件。"""
        enriched = dict(event)
        if request_id is not None:
            enriched["request_id"] = request_id
        if turn_id is not None:
            enriched["turn_id"] = turn_id
        write_event(enriched)

    def read_object() -> dict | None:
        """读取并校验下一条 JSONL 对象；错误行报告后继续读取。"""
        nonlocal had_error
        for line in lines:
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                had_error = True
                emit(
                    {
                        "type": "error",
                        "code": "invalid_json",
                        "message": f"Invalid JSON input: {error.msg}",
                    }
                )
                continue
            if not isinstance(value, dict):
                had_error = True
                emit(
                    {
                        "type": "error",
                        "code": "invalid_request",
                        "message": "Each input line must contain a JSON object.",
                    }
                )
                continue
            return value
        return None

    def run_prompt(text: str, request_id: str | None) -> None:
        """执行一轮模型和工具调用，并在结束时发出终态事件。"""
        nonlocal had_error
        request_id = request_id or uuid4().hex
        turn_id = uuid4().hex
        emit({"type": "turn.started"}, request_id, turn_id)

        def event_sink(event: dict) -> None:
            emit(event, request_id, turn_id)

        def approval_handler(call: dict) -> bool:
            """暂停工具执行，等待 call_id 匹配的明确批准响应。"""
            nonlocal had_error
            emit(
                {
                    "type": "tool.approval_required",
                    **call,
                },
                request_id,
                turn_id,
            )
            while True:
                response = read_object()
                if response is None:
                    return False
                if response.get("type") == "prompt" and initial_prompt is None:
                    queued_prompts.append(response)
                    continue
                if response.get("type") != "approval":
                    had_error = True
                    emit(
                        {
                            "type": "error",
                            "code": "approval_expected",
                            "message": "Expected an approval object for the pending tool call.",
                        },
                        request_id,
                        turn_id,
                    )
                    continue
                if response.get("call_id") != call["call_id"]:
                    had_error = True
                    emit(
                        {
                            "type": "error",
                            "code": "approval_call_id_mismatch",
                            "message": "Approval call_id does not match the pending tool call.",
                        },
                        request_id,
                        turn_id,
                    )
                    continue
                if not isinstance(response.get("approved"), bool):
                    had_error = True
                    emit(
                        {
                            "type": "error",
                            "code": "invalid_approval",
                            "message": "Approval field must be a boolean.",
                        },
                        request_id,
                        turn_id,
                    )
                    continue
                return response["approved"]

        try:
            agent.run_turn(
                text,
                event_sink=event_sink,
                approval_handler=approval_handler,
            )
        except Exception as error:
            had_error = True
            emit(
                {
                    "type": "error",
                    "code": "turn_failed",
                    "message": str(error),
                },
                request_id,
                turn_id,
            )
            emit({"type": "turn.failed"}, request_id, turn_id)
        else:
            emit({"type": "turn.completed"}, request_id, turn_id)

    if initial_prompt is not None:
        if not initial_prompt.strip():
            emit(
                {
                    "type": "error",
                    "code": "invalid_prompt",
                    "message": "Prompt text must be a non-empty string.",
                }
            )
            return 1
        run_prompt(initial_prompt, None)
        return 1 if had_error else 0

    while True:
        request = queued_prompts.popleft() if queued_prompts else read_object()
        if request is None:
            break
        if request.get("type") != "prompt":
            had_error = True
            emit(
                {
                    "type": "error",
                    "code": "unexpected_input",
                    "message": "Expected a prompt request outside tool approval.",
                }
            )
            continue
        text = request.get("text")
        if not isinstance(text, str) or not text.strip():
            had_error = True
            emit(
                {
                    "type": "error",
                    "code": "invalid_prompt",
                    "message": "Prompt text must be a non-empty string.",
                    "request_id": request.get("id"),
                }
            )
            continue
        request_id = request.get("id")
        if request_id is not None and not isinstance(request_id, str):
            had_error = True
            emit(
                {
                    "type": "error",
                    "code": "invalid_request_id",
                    "message": "Prompt id must be a string.",
                }
            )
            continue
        run_prompt(text, request_id)
    return 1 if had_error else 0

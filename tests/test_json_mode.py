"""JSONL protocol tests for prompt, approval, and error event behavior."""

import io
import unittest

from json_mode import run_json_protocol


class FakeAgent:
    mode = "ask"

    def __init__(self, approval=None):
        self.approval = approval
        self.prompts = []

    def run_turn(self, text, *, event_sink, approval_handler):
        self.prompts.append(text)
        event_sink({"type": "assistant.message", "message": {"content": "ok"}})
        if self.approval is not None:
            approved = approval_handler({"call_id": "call-1", "name": "bash"})
            event_sink({"type": "tool.result", "call_id": "call-1", "approved": approved})


class JsonProtocolTests(unittest.TestCase):
    def test_stream_prompt_events_keep_request_and_turn_ids(self):
        agent = FakeAgent()
        events = []
        status = run_json_protocol(
            agent,
            io.StringIO('{"type":"prompt","id":"client-7","text":"hello"}\n'),
            events.append,
        )

        self.assertEqual(status, 0)
        self.assertEqual(agent.prompts, ["hello"])
        turn_events = [event for event in events if "turn_id" in event]
        self.assertTrue(all(event["request_id"] == "client-7" for event in turn_events))
        self.assertEqual(turn_events[0]["type"], "turn.started")
        self.assertEqual(turn_events[-1]["type"], "turn.completed")
        self.assertEqual(len({event["turn_id"] for event in turn_events}), 1)

    def test_approval_is_matched_to_tool_call_id(self):
        agent = FakeAgent(approval=True)
        events = []
        input_data = (
            '{"type":"prompt","text":"run"}\n'
            '{"type":"approval","call_id":"call-1","approved":true}\n'
        )

        status = run_json_protocol(agent, io.StringIO(input_data), events.append)

        self.assertEqual(status, 0)
        self.assertIn("tool.approval_required", [event["type"] for event in events])
        result = next(event for event in events if event["type"] == "tool.result")
        self.assertEqual(result["call_id"], "call-1")
        self.assertTrue(result["approved"])

    def test_invalid_json_is_reported_and_process_returns_failure(self):
        events = []
        status = run_json_protocol(
            FakeAgent(), io.StringIO("{bad json}\n"), events.append
        )

        self.assertEqual(status, 1)
        self.assertEqual(events[0]["code"], "invalid_json")

    def test_one_shot_prompt_rejects_blank_text(self):
        events = []
        status = run_json_protocol(FakeAgent(), io.StringIO(""), events.append, initial_prompt=" ")

        self.assertEqual(status, 1)
        self.assertEqual(events[0]["code"], "invalid_prompt")


if __name__ == "__main__":
    unittest.main()

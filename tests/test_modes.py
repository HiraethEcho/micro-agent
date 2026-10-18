"""Tool approval mode tests."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agent import CommandResult, MicroAgent
from config import MicroConfig


class ToolModeTests(unittest.TestCase):
    def make_agent(self, mode):
        with patch("agent.OpenAI"):
            agent = MicroAgent(MicroConfig(default_mode=mode, allow=["ls *"]))
        return agent

    def test_mode_approval_rules(self):
        self.assertFalse(self.make_agent("yolo")._requires_approval("rm -rf tmp"))
        self.assertTrue(self.make_agent("ask")._requires_approval("pwd"))
        auto = self.make_agent("auto")
        self.assertFalse(auto._requires_approval("ls -la"))
        self.assertTrue(auto._requires_approval("ls -la; rm file"))

    def test_yolo_executes_without_approval_callback(self):
        agent = self.make_agent("yolo")
        agent._run_command = lambda command: CommandResult("done", 0)
        events = []
        call = {
            "id": "tool-1",
            "function": {"name": "bash", "arguments": '{"command":"pwd"}'},
        }

        agent._execute_tool_calls([call], event_sink=events.append)

        result = next(event for event in events if event["type"] == "tool.result")
        self.assertEqual(result["call_id"], "tool-1")
        self.assertTrue(result["approved"])
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(agent.messages[-1]["tool_call_id"], "tool-1")

    def test_ask_rejection_does_not_run_command(self):
        agent = self.make_agent("ask")
        executed = []
        agent._run_command = lambda command: executed.append(command)
        call = {
            "id": "tool-2",
            "function": {"name": "bash", "arguments": '{"command":"pwd"}'},
        }

        agent._execute_tool_calls(
            [call], event_sink=lambda event: None, approval_handler=lambda _: False
        )

        self.assertEqual(executed, [])
        self.assertEqual(agent.messages[-1]["tool_call_id"], "tool-2")
        self.assertEqual(agent.messages[-1]["content"], "Execution rejected by user.")

    def test_turn_emits_correlated_events_across_tool_round_trip(self):
        agent = self.make_agent("yolo")
        call = SimpleNamespace(
            id="tool-3",
            type="function",
            function=SimpleNamespace(
                name="bash", arguments='{"command":"pwd"}'
            ),
            model_dump=lambda **_: {
                "id": "tool-3",
                "type": "function",
                "function": {"name": "bash", "arguments": '{"command":"pwd"}'},
            },
        )
        responses = iter(
            [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content="", tool_calls=[call])
                        )
                    ]
                ),
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content="finished", tool_calls=None)
                        )
                    ]
                ),
            ]
        )
        agent.client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=lambda **_: next(responses))
            )
        )
        agent._messages_with_system_append = lambda: list(agent.messages)
        agent._run_command = lambda command: CommandResult("/project", 0)
        events = []

        agent.run_turn("inspect", event_sink=events.append)

        self.assertEqual(
            [event["type"] for event in events],
            ["assistant.message", "tool.call", "tool.result", "assistant.message"],
        )
        self.assertEqual(events[1]["call_id"], events[2]["call_id"])
        self.assertEqual(agent.messages[-2]["tool_call_id"], "tool-3")
        self.assertEqual(agent.messages[-1]["content"], "finished")


if __name__ == "__main__":
    unittest.main()

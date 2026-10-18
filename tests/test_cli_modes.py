"""CLI coverage for --mode in interactive and JSON execution."""

import unittest
from unittest.mock import patch

from typer.testing import CliRunner

import cli
from config import MicroConfig


class DummySession:
    session_id = "session-1"
    name = None


class DummyAgent:
    def __init__(self, mode="auto"):
        self.mode = mode


class CliModeTests(unittest.TestCase):
    def setUp(self):
        self.runner = CliRunner()

    def test_mode_overrides_config_in_json_mode(self):
        captured = {}
        config = MicroConfig(default_mode="yolo")

        def build_agent(received_config, store):
            captured["mode"] = received_config.default_mode
            return DummyAgent(received_config.default_mode)

        with (
            patch("cli.load_config", return_value=config),
            patch("cli.create_session", return_value=DummySession()),
            patch("cli.build_agent", side_effect=build_agent),
            patch("cli.run_json_protocol", return_value=0),
        ):
            result = self.runner.invoke(cli.app, ["--json", "--mode", "ask", "--no-session"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(captured["mode"], "ask")
        self.assertIn('"mode":"ask"', result.stdout)

    def test_mode_overrides_config_in_interactive_mode(self):
        config = MicroConfig(default_mode="auto")
        with (
            patch("cli.load_config", return_value=config),
            patch("cli.create_session", return_value=DummySession()),
            patch("cli.build_agent", side_effect=lambda config, store: DummyAgent(config.default_mode)),
            patch("cli.PromptSession.prompt", return_value="/quit"),
        ):
            result = self.runner.invoke(cli.app, ["--mode", "yolo"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("mode: yolo", result.stdout)


if __name__ == "__main__":
    unittest.main()

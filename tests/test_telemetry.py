import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch
from scripts.telemetry import (
    get_agent_logs_dir,
    configure_otlp_endpoint,
    init_telemetry,
    start_orchestrator_loop,
    end_orchestrator_loop,
    start_orchestrator_phase,
    end_orchestrator_phase,
)


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        # Backup environment
        self.original_env = dict(os.environ)
        # Create a temp directory for logs
        self.temp_dir = tempfile.mkdtemp()
        os.environ["AGENT_LOG_PATH"] = self.temp_dir

    def tearDown(self):
        # Restore environment
        os.environ.clear()
        os.environ.update(self.original_env)
        # Clean up temp directory
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_get_agent_logs_dir(self):
        """Verify that get_agent_logs_dir honors AGENT_LOG_PATH."""
        logs_dir = get_agent_logs_dir()
        self.assertEqual(os.path.abspath(logs_dir), os.path.abspath(self.temp_dir))
        self.assertTrue(os.path.exists(logs_dir))

    def test_configure_otlp_endpoint(self):
        """Verify configure_otlp_endpoint returns existing env var or docker sentinel default."""
        # 1. When OTEL_EXPORTER_OTLP_ENDPOINT is already set
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://my-endpoint:4317"
        self.assertEqual(configure_otlp_endpoint(), "http://my-endpoint:4317")

        # 2. When unset and not in Docker
        del os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"]
        with patch("os.path.exists", return_value=False):
            self.assertEqual(configure_otlp_endpoint(), "")

        # 3. When unset and in Docker
        with patch("os.path.exists", return_value=True):
            self.assertEqual(
                configure_otlp_endpoint(),
                "http://host.docker.internal:4318/v1/traces",
            )

    def test_telemetry_lifecycle_smoke_test(self):
        """Smoke test to ensure the public API runs without throwing any exceptions."""
        # Setup mock Langfuse environment variables
        os.environ["LANGFUSE_PUBLIC_KEY"] = "pk-lf-test"
        os.environ["LANGFUSE_SECRET_KEY"] = "sk-lf-test"
        os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = "custom-header=value"

        # Initialize telemetry (registers provider/exporters)
        init_telemetry()

        # Run loops and phases
        start_orchestrator_loop(issue_number=42, session_id="sess-1", user_id="user-2")
        start_orchestrator_phase("test_phase")
        end_orchestrator_phase(
            exit_code=0,
            prompt_tokens=10,
            completion_tokens=20,
            model_name="gpt-4",
        )
        end_orchestrator_loop(exit_code=0)

        # Verify that local log file got created
        files = os.listdir(self.temp_dir)
        otel_log_files = [
            f for f in files if f.startswith("otel_traces_") and f.endswith(".jsonl")
        ]
        self.assertTrue(len(otel_log_files) >= 1)

        # Inspect the content of the trace file to make sure attributes/spans are recorded
        log_file_path = os.path.join(self.temp_dir, otel_log_files[0])
        with open(log_file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        self.assertTrue(len(lines) >= 2)  # At least loop and phase spans

        found_loop = False
        found_phase = False
        for line in lines:
            data = json.loads(line)
            if data["name"] == "orchestrator_loop":
                found_loop = True
                self.assertEqual(data["attributes"].get("issue.number"), 42)
                self.assertEqual(
                    data["attributes"].get("langfuse.session.id"), "sess-1"
                )
                self.assertEqual(data["attributes"].get("langfuse.user.id"), "user-2")
            elif data["name"] == "orchestrator_phase_test_phase":
                found_phase = True
                self.assertEqual(data["attributes"].get("phase"), "test_phase")
                self.assertEqual(data["attributes"].get("llm.model_name"), "gpt-4")
                self.assertEqual(data["attributes"].get("llm.usage.prompt_tokens"), 10)
                self.assertEqual(
                    data["attributes"].get("llm.usage.completion_tokens"), 20
                )
                self.assertEqual(
                    data["attributes"].get("langfuse.session.id"), "sess-1"
                )
                self.assertEqual(data["attributes"].get("langfuse.user.id"), "user-2")

        self.assertTrue(found_loop)
        self.assertTrue(found_phase)

    def test_telemetry_isolation(self):
        """Verify that starting a new loop run resets and isolates telemetry context/baggage."""
        init_telemetry()

        # Run 1: Left unfinished (simulating crash)
        start_orchestrator_loop(issue_number=101, session_id="sess-A", user_id="user-A")
        start_orchestrator_phase("phase_left_open")

        # Run 2: Started in the same thread/process context
        start_orchestrator_loop(issue_number=102, session_id="sess-B", user_id="user-B")
        start_orchestrator_phase("phase_normal")
        end_orchestrator_phase(exit_code=0)
        end_orchestrator_loop(exit_code=0)

        # Inspect the logs
        files = os.listdir(self.temp_dir)
        otel_log_files = [
            f for f in files if f.startswith("otel_traces_") and f.endswith(".jsonl")
        ]
        log_file_path = os.path.join(self.temp_dir, otel_log_files[0])
        with open(log_file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # Let's inspect the normal phase and loop of Run 2
        for line in lines:
            data = json.loads(line)
            if data["name"] == "orchestrator_phase_phase_normal":
                # Ensure it has Run 2 baggage only, and not Run 1's baggage!
                self.assertEqual(
                    data["attributes"].get("langfuse.session.id"), "sess-B"
                )
                self.assertEqual(data["attributes"].get("langfuse.user.id"), "user-B")
            elif (
                data["name"] == "orchestrator_loop"
                and data["attributes"].get("issue.number") == 102
            ):
                self.assertEqual(
                    data["attributes"].get("langfuse.session.id"), "sess-B"
                )
                self.assertEqual(data["attributes"].get("langfuse.user.id"), "user-B")

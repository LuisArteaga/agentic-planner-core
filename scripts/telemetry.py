import base64
import os
import sys
import json
import datetime
import threading
from pathlib import Path

from opentelemetry import trace, context, baggage
from opentelemetry.sdk.trace import TracerProvider, SpanProcessor
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, BatchSpanProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.trace import set_span_in_context

# Literal keys from OpenInference Semantic Conventions
OPENINFERENCE_SPAN_KIND = "openinference.span.kind"
INPUT_VALUE = "input.value"
OUTPUT_VALUE = "output.value"
LLM_MODEL_NAME = "llm.model_name"
TOOL_NAME = "tool.name"
TOOL_PARAMETERS = "tool.parameters"

_DOCKER_SENTINEL = "/.dockerenv"
_DEFAULT_OTLP_ENDPOINT = "http://host.docker.internal:4318/v1/traces"


def _is_docker() -> bool:
    """Return True when running inside a Docker container."""
    return os.path.exists(_DOCKER_SENTINEL)


def configure_otlp_endpoint() -> str:
    """Return the OTLP endpoint to use, defaulting to host.docker.internal when in Docker.

    If OTEL_EXPORTER_OTLP_ENDPOINT is already set in the environment, that value is
    returned unchanged. Otherwise, if /.dockerenv is present, the default
    http://host.docker.internal:4318/v1/traces endpoint is set and returned.
    Returns an empty string when neither condition applies.
    """
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if not endpoint and _is_docker():
        endpoint = _DEFAULT_OTLP_ENDPOINT
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = endpoint
    return endpoint


def get_tracer():
    """Returns the central tracer instance."""
    return trace.get_tracer("agentic-planner-core")


def get_agent_logs_dir() -> str:
    """Resolve and return the path to the agent logs directory, ensuring it exists and is writable."""
    # First check if AGENT_LOG_PATH is configured in the environment
    agent_log_path = os.getenv("AGENT_LOG_PATH")
    if agent_log_path:
        try:
            os.makedirs(agent_log_path, exist_ok=True)
            if os.access(agent_log_path, os.W_OK):
                return str(Path(agent_log_path).resolve())
        except Exception:
            pass

    # Fallback to checking /workspace/.agent_logs (inside container)
    if os.path.exists("/workspace/.agent_logs") and os.access("/workspace/.agent_logs", os.W_OK):
        return "/workspace/.agent_logs"
    # Otherwise check local .agent_logs relative to current working dir or project root
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    local_logs = os.path.join(project_root, ".agent_logs")
    try:
        os.makedirs(local_logs, exist_ok=True)
        if os.access(local_logs, os.W_OK):
            return local_logs
    except Exception:
        pass
    # Fallback to temp logs if nothing else works
    tmp_logs = "/tmp/agent_logs"
    try:
        os.makedirs(tmp_logs, mode=0o700, exist_ok=True)
        os.chmod(tmp_logs, 0o700)
    except Exception:
        pass
    return tmp_logs


class LocalJSONLFileSpanProcessor(SpanProcessor):
    """A custom OpenTelemetry SpanProcessor that serializes finished spans to local JSONL files."""

    def __init__(self):
        self._lock = threading.Lock()

    def on_start(self, span, parent_context=None):
        # Automatically copy baggage keys starting with 'langfuse.' to span attributes
        try:
            ctx = parent_context if parent_context is not None else context.get_current()
            baggage_entries = baggage.get_all(ctx)
            for k, v in baggage_entries.items():
                if k.startswith("langfuse."):
                    span.set_attribute(k, v)
        except Exception as e:
            sys.stderr.write(
                f"[WARN] LocalJSONLFileSpanProcessor failed to copy baggage: {e}\n"
            )

    def on_end(self, span):
        try:
            status_code = (
                span.status.status_code.value
                if hasattr(span.status.status_code, "value")
                else int(span.status.status_code)
            )
            status_description = span.status.description or ""

            span_dict = {
                "trace_id": f"{span.context.trace_id:032x}",
                "span_id": f"{span.context.span_id:016x}",
                "parent_span_id": (
                    f"{span.parent.span_id:016x}" if span.parent else ""
                ),
                "name": span.name,
                "kind": (
                    span.kind.value
                    if hasattr(span.kind, "value")
                    else int(span.kind)
                ),
                "start_time_unix_nano": span.start_time,
                "end_time_unix_nano": span.end_time,
                "attributes": dict(span.attributes or {}),
                "status_code": status_code,
                "status_message": status_description,
                "resource_attributes": dict(span.resource.attributes or {}),
                "scope_name": (
                    span.instrumentation_scope.name
                    if span.instrumentation_scope
                    else "unknown"
                ),
            }

            # Write to dated file
            today_str = datetime.date.today().isoformat()
            logs_dir = get_agent_logs_dir()
            log_file_path = os.path.join(
                logs_dir, f"otel_traces_{today_str}.jsonl"
            )

            with self._lock:
                with open(log_file_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(span_dict) + "\n")
                    f.flush()
        except Exception as e:
            sys.stderr.write(
                f"[WARN] LocalJSONLFileSpanProcessor failed to write span: {e}\n"
            )

    def shutdown(self):
        pass

    def force_flush(self, timeout_millis=30000):
        return True


# Thread-local storage to track active spans on the execution context
_local_state = threading.local()


def _get_local_state():
    if not hasattr(_local_state, "loop_span"):
        _local_state.loop_span = None
    if not hasattr(_local_state, "loop_token"):
        _local_state.loop_token = None
    if not hasattr(_local_state, "active_phases"):
        _local_state.active_phases = {}
    return _local_state


def init_telemetry(in_memory_exporter=None):
    """Initializes OpenTelemetry TracerProvider and registers exporters."""
    current_provider = trace.get_tracer_provider()
    if isinstance(current_provider, TracerProvider):
        if in_memory_exporter is not None:
            current_provider.add_span_processor(
                SimpleSpanProcessor(in_memory_exporter)
            )
        return

    service_name = os.getenv("OTEL_SERVICE_NAME", "agentic-planner-core")
    resource = Resource.create({
        "service.name": service_name,
    })

    provider = TracerProvider(resource=resource)

    # Register local crash-resistant logging processor
    provider.add_span_processor(LocalJSONLFileSpanProcessor())

    if in_memory_exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(in_memory_exporter))
    else:
        # Determine endpoints and authorization headers
        pub_key = os.getenv("LANGFUSE_PUBLIC_KEY", "")
        sec_key = os.getenv("LANGFUSE_SECRET_KEY", "")

        # Default OTLP endpoint to Langfuse Cloud if keys are configured
        if pub_key and sec_key and not os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
            os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = (
                "https://cloud.langfuse.com/api/public/otel"
            )

        configure_otlp_endpoint()
        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
        if endpoint:
            if not endpoint.endswith("/v1/traces"):
                endpoint = endpoint.rstrip("/") + "/v1/traces"

            headers = {}
            if pub_key and sec_key:
                auth_str = f"{pub_key}:{sec_key}"
                encoded_auth = base64.b64encode(
                    auth_str.encode("utf-8")
                ).decode("utf-8")
                headers["Authorization"] = f"Basic {encoded_auth}"

            extra_headers_str = os.getenv("OTEL_EXPORTER_OTLP_HEADERS", "")
            if extra_headers_str:
                for item in extra_headers_str.split(","):
                    if "=" in item:
                        k, v = item.split("=", 1)
                        headers[k.strip()] = v.strip()

            try:
                exporter = OTLPSpanExporter(endpoint=endpoint, headers=headers)
                provider.add_span_processor(BatchSpanProcessor(exporter))
            except Exception as e:
                sys.stderr.write(
                    f"[WARN] Failed to initialize OTLP exporter: {e}\n"
                )

    trace.set_tracer_provider(provider)


def start_orchestrator_loop(issue_number=None, session_id=None, user_id=None):
    """Start the parent orchestrator_loop span."""
    state = _get_local_state()
    tracer = get_tracer()

    span = tracer.start_span(
        "orchestrator_loop", attributes={OPENINFERENCE_SPAN_KIND: "CHAIN"}
    )
    if issue_number is not None:
        span.set_attribute("issue.number", issue_number)
    if session_id is not None:
        span.set_attribute("langfuse.session.id", str(session_id))
    if user_id is not None:
        span.set_attribute("langfuse.user.id", str(user_id))

    state.loop_span = span

    ctx = context.get_current()
    if session_id is not None:
        ctx = baggage.set_baggage("langfuse.session.id", str(session_id), ctx)
    if user_id is not None:
        ctx = baggage.set_baggage("langfuse.user.id", str(user_id), ctx)

    ctx = set_span_in_context(span, ctx)
    state.loop_token = context.attach(ctx)
    return span


def end_orchestrator_loop(exit_code=0):
    """End the active orchestrator_loop span."""
    state = _get_local_state()

    open_phases = list(state.active_phases.keys())
    for phase_name in open_phases:
        end_orchestrator_phase(exit_code=exit_code)

    if state.loop_span is not None:
        span = state.loop_span
        span.set_attribute("command.exit_code", exit_code)
        status_code = (
            trace.StatusCode.OK if exit_code == 0 else trace.StatusCode.ERROR
        )
        span.set_status(
            trace.Status(
                status_code,
                f"exit code {exit_code}" if exit_code != 0 else None,
            )
        )
        span.end()
        state.loop_span = None

    if state.loop_token is not None:
        context.detach(state.loop_token)
        state.loop_token = None


def start_orchestrator_phase(phase_name):
    """Start a nested span for one of the orchestrator phases."""
    state = _get_local_state()
    tracer = get_tracer()

    span = tracer.start_span(
        f"orchestrator_phase_{phase_name}",
        attributes={OPENINFERENCE_SPAN_KIND: "CHAIN", "phase": phase_name},
    )

    ctx = set_span_in_context(span)
    token = context.attach(ctx)

    state.active_phases[phase_name] = (span, token)
    return span


def end_orchestrator_phase(
    exit_code=0, prompt_tokens=None, completion_tokens=None, model_name=None
):
    """End the active orchestrator phase span."""
    state = _get_local_state()

    if not state.active_phases:
        return

    phase_name, (span, token) = state.active_phases.popitem()

    span.set_attribute("command.exit_code", exit_code)
    if prompt_tokens is not None:
        span.set_attribute("llm.usage.prompt_tokens", prompt_tokens)
    if completion_tokens is not None:
        span.set_attribute("llm.usage.completion_tokens", completion_tokens)
    if model_name is not None:
        span.set_attribute("llm.model_name", model_name)

    status_code = (
        trace.StatusCode.OK if exit_code == 0 else trace.StatusCode.ERROR
    )
    span.set_status(
        trace.Status(
            status_code, f"exit code {exit_code}" if exit_code != 0 else None
        )
    )
    span.end()

    context.detach(token)

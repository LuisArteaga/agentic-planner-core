import os
import tempfile
import pytest
import tomli_w
from unittest.mock import patch
from planner.config import AppConfig


@pytest.fixture
def clean_env():
    # Save current environment and clean up keys for testing
    old_env = dict(os.environ)
    for key in [
        "OPENROUTER_API_KEY",
        "GH_PAT",
        "GITHUB_REPOSITORY",
        "GITHUB_WORKSPACE",
    ]:
        if key in os.environ:
            del os.environ[key]
    # Clear all *_MODEL override env vars so .env model overrides (e.g.
    # GRILL_MODEL) don't leak into tests asserting factory-driven config (#58).
    for key in [k for k in list(os.environ) if k.endswith("_MODEL")]:
        del os.environ[key]
    # Prevent resolve_model_config's load_env_file() (config.py:236) and
    # AppConfig.__init__ (config.py:96) from re-populating .env overrides during
    # the test (#58). Without this, clearing *_MODEL above is undone because
    # load_env_file sets keys that are not already in os.environ.
    with patch("planner.config.load_env_file", lambda *a, **k: None):
        yield
    # Restore original environment
    os.environ.clear()
    os.environ.update(old_env)


def create_temp_toml(data):
    temp = tempfile.NamedTemporaryFile(delete=False, suffix=".toml", mode="wb")
    temp.write(tomli_w.dumps(data).encode("utf-8"))
    temp.close()
    return temp.name


def test_missing_env_vars(clean_env):
    temp_file = create_temp_toml({"strict": False})
    with pytest.raises(ValueError) as exc:
        AppConfig(sources_toml_path=temp_file)
    assert "Missing required environment variable(s)" in str(exc.value)
    os.unlink(temp_file)


def test_valid_config(clean_env):
    os.environ["OPENROUTER_API_KEY"] = "test-key"
    os.environ["GH_PAT"] = "test-pat"
    os.environ["GITHUB_REPOSITORY"] = "test/repo"

    toml_data = {
        "strict": True,
        "urls": ["https://github.com/test/repo-allowed"],
        "domains": ["example.com"],
    }
    temp_file = create_temp_toml(toml_data)

    config = AppConfig(sources_toml_path=temp_file)
    assert config.openrouter_api_key == "test-key"
    assert config.sources.strict is True
    assert "https://github.com/test/repo-allowed" in config.sources.urls
    assert "example.com" in config.sources.domains

    os.unlink(temp_file)


def test_strict_mode_without_sources(clean_env):
    os.environ["OPENROUTER_API_KEY"] = "test-key"
    os.environ["GH_PAT"] = "test-pat"
    os.environ["GITHUB_REPOSITORY"] = "test/repo"

    toml_data = {"strict": True, "urls": [], "domains": []}
    temp_file = create_temp_toml(toml_data)

    with pytest.raises(ValueError) as exc:
        AppConfig(sources_toml_path=temp_file)
    assert "At least one source must be defined" in str(exc.value)

    os.unlink(temp_file)


def test_github_workspace_resolution(clean_env):
    os.environ["OPENROUTER_API_KEY"] = "test-key"
    os.environ["GH_PAT"] = "test-pat"
    os.environ["GITHUB_REPOSITORY"] = "test/repo"

    toml_data = {"strict": False}
    temp_file = create_temp_toml(toml_data)

    # 1. Test relative path resolution
    os.environ["GITHUB_WORKSPACE"] = "sub/dir"
    config = AppConfig(sources_toml_path=temp_file)
    from pathlib import Path

    expected_root = Path(__file__).resolve().parents[1]
    assert config.github_workspace == str(
        (expected_root / ".workspaces" / "sub/dir").resolve()
    )
    assert os.environ["GITHUB_WORKSPACE"] == config.github_workspace

    # 2. Test absolute path resolution
    import tempfile as tf

    with tf.TemporaryDirectory() as tmpdir:
        os.environ["GITHUB_WORKSPACE"] = tmpdir
        config = AppConfig(sources_toml_path=temp_file)
        assert config.github_workspace == str(Path(tmpdir).resolve())
        assert os.environ["GITHUB_WORKSPACE"] == config.github_workspace

    # 3. Test default fallback when unset
    if "GITHUB_WORKSPACE" in os.environ:
        del os.environ["GITHUB_WORKSPACE"]
    config = AppConfig(sources_toml_path=temp_file)
    assert config.github_workspace == os.getcwd()
    assert os.environ["GITHUB_WORKSPACE"] == os.getcwd()

    # 4. Test path traversal prevention for relative GITHUB_WORKSPACE
    os.environ["GITHUB_WORKSPACE"] = "../../../etc"
    with pytest.raises(ValueError) as exc:
        AppConfig(sources_toml_path=temp_file)
    assert "Path traversal detected" in str(exc.value)

    os.unlink(temp_file)


def test_factory_config_invalid_json(clean_env):
    os.environ["OPENROUTER_API_KEY"] = "test-key"
    os.environ["GH_PAT"] = "test-pat"
    os.environ["GITHUB_REPOSITORY"] = "test/repo"

    sources_temp = create_temp_toml({"strict": False})
    # Create invalid json file
    temp_json = tempfile.NamedTemporaryFile(
        delete=False, suffix=".json", mode="w", encoding="utf-8"
    )
    temp_json.write("{invalid json: }")
    temp_json.close()

    with pytest.raises(ValueError) as exc:
        AppConfig(sources_toml_path=sources_temp, factory_json_path=temp_json.name)
    assert "Invalid JSON format" in str(exc.value)

    os.unlink(sources_temp)
    os.unlink(temp_json.name)


def test_factory_config_missing_file(clean_env):
    os.environ["OPENROUTER_API_KEY"] = "test-key"
    os.environ["GH_PAT"] = "test-pat"
    os.environ["GITHUB_REPOSITORY"] = "test/repo"

    sources_temp = create_temp_toml({"strict": False})

    with pytest.raises(FileNotFoundError) as exc:
        AppConfig(
            sources_toml_path=sources_temp, factory_json_path="nonexistent_factory.json"
        )
    assert "Factory configuration file not found" in str(exc.value)

    os.unlink(sources_temp)


def test_sources_falls_back_to_example_on_fresh_clone(clean_env, caplog):
    """ADR-0024: without the untracked personal sources.toml, the tracked
    example configuration loads so a fresh clone starts cleanly."""
    import logging

    os.environ["OPENROUTER_API_KEY"] = "test-key"
    os.environ["GH_PAT"] = "test-pat"
    os.environ["GITHUB_REPOSITORY"] = "test/repo"

    missing_default = create_temp_toml({"strict": False})
    os.unlink(missing_default)

    with caplog.at_level(logging.WARNING):
        with patch("planner.config.DEFAULT_SOURCES_PATH", missing_default):
            config = AppConfig(sources_toml_path=missing_default)

    # The example file's content is the observable proof the fallback loaded.
    assert config.sources.strict is True
    assert "https://github.com/langchain-ai/langgraph" in config.sources.urls
    assert "arxiv.org" in config.sources.domains
    fallback_warnings = [
        rec
        for rec in caplog.records
        if rec.name == "planner.config" and rec.levelno == logging.WARNING
    ]
    assert fallback_warnings


def test_sources_missing_without_example_raises(clean_env):
    """ADR-0024: with neither the default nor the example file present,
    startup still fails loudly with the standard FileNotFoundError."""
    os.environ["OPENROUTER_API_KEY"] = "test-key"
    os.environ["GH_PAT"] = "test-pat"
    os.environ["GITHUB_REPOSITORY"] = "test/repo"

    missing_default = create_temp_toml({"strict": False})
    os.unlink(missing_default)
    missing_example = create_temp_toml({"strict": False})
    os.unlink(missing_example)

    with (
        patch("planner.config.DEFAULT_SOURCES_PATH", missing_default),
        patch("planner.config.EXAMPLE_SOURCES_PATH", missing_example),
    ):
        with pytest.raises(FileNotFoundError) as exc:
            AppConfig(sources_toml_path=missing_default)
    assert "Configuration file not found" in str(exc.value)


def test_sources_invalid_toml_raises(clean_env):
    """A malformed sources file fails loudly, regardless of fallback state."""
    os.environ["OPENROUTER_API_KEY"] = "test-key"
    os.environ["GH_PAT"] = "test-pat"
    os.environ["GITHUB_REPOSITORY"] = "test/repo"

    temp_file = tempfile.NamedTemporaryFile(
        delete=False, suffix=".toml", mode="w", encoding="utf-8"
    )
    temp_file.write("this is not valid toml")
    temp_file.close()

    with pytest.raises(ValueError) as exc:
        AppConfig(sources_toml_path=temp_file.name)
    assert "Invalid TOML format" in str(exc.value)

    os.unlink(temp_file.name)


def test_factory_config_optional_on_fresh_clone(clean_env):
    """ADR-0024: without the untracked personal factory.json, startup skips
    factory validation and model resolution uses the built-in defaults."""
    os.environ["OPENROUTER_API_KEY"] = "test-key"
    os.environ["GH_PAT"] = "test-pat"
    os.environ["GITHUB_REPOSITORY"] = "test/repo"

    sources_temp = create_temp_toml({"strict": False})
    missing_factory = create_temp_toml({"strict": False})
    os.unlink(missing_factory)

    with patch("planner.config.DEFAULT_FACTORY_PATH", missing_factory):
        config = AppConfig(
            sources_toml_path=sources_temp, factory_json_path=missing_factory
        )
    assert config is not None

    # Model resolution survives without factory.json: the built-in defaults
    # apply (the loader raising FileNotFoundError is the fresh-clone state).
    from planner.config import resolve_model_config

    with patch("planner.config._load_factory_config", side_effect=FileNotFoundError):
        cfg = resolve_model_config("grill")
    assert cfg["model"] == "z-ai/glm-5.2"

    os.unlink(sources_temp)


def test_resolve_model_config_overrides(clean_env):
    # Test resolve_model_config with env overrides
    os.environ["AGENT_MODEL"] = "env-agent-model"
    os.environ["PR_SYNTAX_LINT_MODEL"] = "syntax-model-override"

    from planner.config import resolve_model_config

    cfg = resolve_model_config("syntax_lint")
    assert cfg["model"] == "syntax-model-override"
    assert cfg["routing"] is None  # routing is disabled for overrides

    cfg_test = resolve_model_config("test_coverage")
    assert cfg_test["model"] == "env-agent-model"
    assert cfg_test["routing"] is None


def test_factory_config_positive_parsing(clean_env):
    os.environ["OPENROUTER_API_KEY"] = "test-key"
    os.environ["GH_PAT"] = "test-pat"
    os.environ["GITHUB_REPOSITORY"] = "test/repo"

    sources_temp = create_temp_toml({"strict": False})
    # Create valid factory json
    valid_factory_data = {
        "factory_version": "2026.2.0",
        "cli_orchestration": {
            "grill": {
                "model": "z-ai/glm-5.2",
                "routing": ["Friendli"],
                "temperature": 0.5,
            }
        },
        "refine_graph_nodes": {
            "analyze_sources": {
                "model": "deepseek/deepseek-v4-flash",
                "options": {"thinking": "high"},
            }
        },
        "ci_cd_pr_judges": {"syntax_lint": {"model": "moonshotai/kimi-k2.7-code"}},
    }

    temp_json = tempfile.NamedTemporaryFile(
        delete=False, suffix=".json", mode="w", encoding="utf-8"
    )
    import json

    json.dump(valid_factory_data, temp_json)
    temp_json.close()

    # Verify AppConfig starts successfully with valid factory.json
    config = AppConfig(sources_toml_path=sources_temp, factory_json_path=temp_json.name)
    assert config is not None

    # Verify resolve_model_config fallback logic reads from our factory
    from planner.config import resolve_model_config

    # Force _load_factory_config to return our custom mocked factory
    from unittest.mock import patch

    with patch("planner.config._load_factory_config") as mock_load:
        from planner.config import FactoryConfig

        mock_load.return_value = FactoryConfig.model_validate(valid_factory_data)

        # 1. Resolve grill from factory (using custom temperature)
        cfg_grill = resolve_model_config("grill")
        assert cfg_grill["model"] == "z-ai/glm-5.2"
        assert cfg_grill["routing"] == ["Friendli"]
        assert cfg_grill["temperature"] == 0.5

        # 2. Resolve evaluate_grade (not in factory orchestration -> uses code defaults)
        cfg_grade = resolve_model_config("evaluate_grade")
        assert cfg_grade["model"] == "z-ai/glm-5.2"  # default
        assert cfg_grade["routing"] == [
            "Together",
            "DeepInfra",
            "Fireworks",
            "Parasail",
            "Inceptron",
        ]  # default_routing fallback
        assert cfg_grade["temperature"] == 0.0  # default

    os.unlink(sources_temp)
    os.unlink(temp_json.name)


def test_get_llm_construction(clean_env):
    os.environ["OPENROUTER_API_KEY"] = "test-key"
    os.environ["GH_PAT"] = "test-pat"
    os.environ["GITHUB_REPOSITORY"] = "test/repo"

    from planner.config import get_llm
    from unittest.mock import patch, MagicMock

    with patch("planner.config.resolve_model_config") as mock_resolve:
        mock_resolve.return_value = {
            "model": "deepseek/deepseek-v4-pro",
            "routing": ["Together", "Novita"],
            "temperature": 0.2,
            "options": {"thinking": "max"},
            "max_tokens": 16384,
        }

        # Mock the OpenRouter-aware subclass to avoid real instantiation overhead
        with patch("planner.config.OpenRouterAnnotationChatOpenAI") as mock_cls:
            mock_cls.return_value = MagicMock()

            client = get_llm("draft")
            assert client is not None

            mock_cls.assert_called_once()
            called_kwargs = mock_cls.call_args[1]
            assert called_kwargs["model"] == "deepseek/deepseek-v4-pro"
            assert called_kwargs["temperature"] == 0.2
            assert called_kwargs["max_tokens"] == 16384
            assert called_kwargs["openai_api_base"] == "https://openrouter.ai/api/v1"
            assert called_kwargs["openai_api_key"] == "test-key"
            assert called_kwargs["use_responses_api"] is False
            import httpx as _httpx

            timeout = called_kwargs["timeout"]
            assert isinstance(timeout, _httpx.Timeout)
            # read == configured timeout_seconds (default 600); connect/write/pool tight.
            assert timeout.read == 600.0
            assert timeout.connect == 10.0
            assert timeout.write == 30.0
            assert timeout.pool == 30.0
            # No silent SDK retry stacking (ADR-0021).
            assert called_kwargs["max_retries"] == 0

            # extra_body is passed as a first-class kwarg (NOT nested in model_kwargs)
            extra_body = called_kwargs["extra_body"]
            assert extra_body["provider"] == {
                "order": ["together", "novita"],
                "allow_fallbacks": False,
            }
            assert extra_body["thinking"] == "max"
            assert "extra_body" not in (called_kwargs.get("model_kwargs") or {})

    # An explicit max_tokens_override takes precedence over the configured value
    # (used by the apply_decision retry loop on truncation, #56).
    with patch("planner.config.resolve_model_config") as mock_resolve:
        mock_resolve.return_value = {
            "model": "deepseek/deepseek-v4-pro",
            "routing": None,
            "temperature": 0.2,
            "options": None,
            "max_tokens": 16384,
        }
        with patch("planner.config.OpenRouterAnnotationChatOpenAI") as mock_cls:
            mock_cls.return_value = MagicMock()
            get_llm("apply_decision", max_tokens_override=32768)
            assert mock_cls.call_args[1]["max_tokens"] == 32768


def test_search_config_parsing_and_overlap(clean_env, caplog):
    os.environ["OPENROUTER_API_KEY"] = "test-key"
    os.environ["GH_PAT"] = "test-pat"
    os.environ["GITHUB_REPOSITORY"] = "test/repo"

    # 1. Test standard parsing of search config
    toml_data = {
        "strict": True,
        "urls": ["https://github.com/test/repo-allowed"],
        "domains": ["example.com"],
        "search": {
            "engine": "exa",
            "search_context_size": "medium",
            "max_results": 5,
            "max_total_results": 15,
            "excluded_domains": ["REDDIT.COM ", "stackoverflow.com"],
        },
    }
    temp_file = create_temp_toml(toml_data)
    config = AppConfig(sources_toml_path=temp_file)

    assert config.sources.search.engine == "exa"
    assert config.sources.search.search_context_size == "medium"
    assert config.sources.search.max_results == 5
    assert config.sources.search.max_total_results == 15
    # Normalization check (lowercase and strip)
    assert "reddit.com" in config.sources.search.excluded_domains
    assert "stackoverflow.com" in config.sources.search.excluded_domains

    os.unlink(temp_file)

    # 2. Test overlap detection and warning logging
    toml_data_overlap = {
        "strict": True,
        "urls": ["https://github.com/test/repo-allowed"],
        "domains": ["example.com"],
        "search": {
            "engine": "auto",
            "excluded_domains": ["EXAMPLE.COM"],  # Overlaps with domains
        },
    }
    temp_file_overlap = create_temp_toml(toml_data_overlap)

    import logging

    with caplog.at_level(logging.WARNING):
        # Trigger validation overlap warning
        AppConfig(sources_toml_path=temp_file_overlap)

    # Verify warning was logged
    warnings = [rec.message for rec in caplog.records if rec.levelno == logging.WARNING]
    assert any("Overlap detected: Domain 'example.com'" in w for w in warnings)

    os.unlink(temp_file_overlap)


def test_get_github_session_timeout(clean_env):
    os.environ["OPENROUTER_API_KEY"] = "test-key"
    os.environ["GH_PAT"] = "test-pat"
    os.environ["GITHUB_REPOSITORY"] = "test/repo"

    from planner.config import AppConfig
    import requests

    config = AppConfig()
    session = config.get_github_session()
    assert isinstance(session, requests.Session)

    # Verify that the session request method wraps calls and adds default timeout
    from unittest.mock import patch, MagicMock

    # Mock requests.Session.send method
    with patch("requests.Session.send") as mock_send:
        mock_send.return_value = MagicMock()
        # Call session.get or session.post without timeout
        session.get("https://api.github.com/some_endpoint")
        mock_send.assert_called_once()
        called_kwargs = mock_send.call_args[1]
        assert called_kwargs["timeout"] == 60.0

    # Verify that explicit timeout overrides the default
    with patch("requests.Session.send") as mock_send:
        mock_send.return_value = MagicMock()
        session.get("https://api.github.com/some_endpoint", timeout=15.0)
        mock_send.assert_called_once()
        called_kwargs = mock_send.call_args[1]
        assert called_kwargs["timeout"] == 15.0


def test_cli_planning_get_llm_timeout(clean_env):
    os.environ["OPENROUTER_API_KEY"] = "test-key"
    os.environ["GH_PAT"] = "test-pat"
    os.environ["GITHUB_REPOSITORY"] = "test/repo"

    from planner.config import AppConfig
    from planner.cli_planning import get_llm
    from unittest.mock import patch, MagicMock

    config = AppConfig()

    with patch("planner.cli_planning.ChatOpenAI") as mock_chat_openai:
        mock_chat_openai.return_value = MagicMock()
        client = get_llm(config, model_name="test-model")
        assert client is not None
        mock_chat_openai.assert_called_once()
        called_kwargs = mock_chat_openai.call_args[1]
        assert called_kwargs["timeout"] == 600.0


def test_openrouter_chat_openai_captures_url_citation_annotations(clean_env):
    """The subclass must preserve url_citation annotations that base ChatOpenAI drops.

    Uses a plain-dict Chat Completions response (the override supports both dict
    and typed responses) to exercise the same capture logic without coupling the
    test to the OpenAI SDK's typed annotation models.
    """
    from pydantic import SecretStr
    from planner.config import OpenRouterAnnotationChatOpenAI

    llm = OpenRouterAnnotationChatOpenAI(
        model="test-model",
        api_key=SecretStr("k"),
        base_url="http://x",
        use_responses_api=False,
    )
    resp = {
        "id": "c1",
        "created": 1,
        "model": "test-model",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": "Findings.",
                    "annotations": [
                        {
                            "type": "url_citation",
                            "url_citation": {
                                "url": "https://example.com/a",
                                "title": "A",
                                "content": "snippet A",
                                "start_index": 0,
                                "end_index": 5,
                            },
                        }
                    ],
                },
            }
        ],
    }

    result = llm._create_chat_result(resp)
    ai = result.generations[0].message
    anns = ai.additional_kwargs.get("annotations")
    assert anns is not None
    assert len(anns) == 1
    assert anns[0]["type"] == "url_citation"
    assert anns[0]["url_citation"]["url"] == "https://example.com/a"


def test_openrouter_chat_openai_extra_body_passed_directly(clean_env):
    """extra_body must be a first-class kwarg, NOT nested under model_kwargs (Bug 2)."""
    import warnings
    from pydantic import SecretStr
    from planner.config import OpenRouterAnnotationChatOpenAI

    extra = {"provider": {"order": ["anthropic"], "allow_fallbacks": False}}
    with warnings.catch_warnings():
        warnings.simplefilter(
            "error"
        )  # the old model_kwargs approach raises UserWarning
        llm = OpenRouterAnnotationChatOpenAI(
            model="test-model",
            api_key=SecretStr("k"),
            base_url="http://x",
            use_responses_api=False,
            extra_body=extra,
        )
    assert llm.extra_body == extra
    assert "extra_body" not in (llm.model_kwargs or {})


def test_get_llm_returns_subclass_without_extra_body_in_model_kwargs(clean_env):
    """get_llm returns the OpenRouter-aware subclass and never nests extra_body."""
    os.environ["OPENROUTER_API_KEY"] = "test-key"
    os.environ["GH_PAT"] = "test-pat"
    os.environ["GITHUB_REPOSITORY"] = "test/repo"

    import warnings
    from planner.config import get_llm, OpenRouterAnnotationChatOpenAI

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        llm = get_llm("web_search")
    assert isinstance(llm, OpenRouterAnnotationChatOpenAI)
    assert "extra_body" not in (llm.model_kwargs or {})


def test_get_llm_factory_timeout_and_retry_overrides(clean_env):
    """Per-node ``timeout_seconds``/``max_retries`` overrides flow into the client (ADR-0021)."""
    os.environ["OPENROUTER_API_KEY"] = "test-key"
    os.environ["GH_PAT"] = "test-pat"
    os.environ["GITHUB_REPOSITORY"] = "test/repo"

    import httpx as _httpx
    from unittest.mock import patch, MagicMock
    from planner.config import get_llm

    with patch("planner.config.resolve_model_config") as mock_resolve:
        mock_resolve.return_value = {
            "model": "deepseek/deepseek-v4-pro",
            "routing": None,
            "temperature": 0.0,
            "options": None,
            "max_tokens": 8192,
            "timeout_seconds": 120.0,
            "max_retries": 1,
        }
        with patch("planner.config.OpenRouterAnnotationChatOpenAI") as mock_cls:
            mock_cls.return_value = MagicMock()
            get_llm("propose_options")
            called_kwargs = mock_cls.call_args[1]
            timeout = called_kwargs["timeout"]
            assert isinstance(timeout, _httpx.Timeout)
            assert timeout.read == 120.0  # factory override honored
            assert timeout.connect == 10.0
            assert called_kwargs["max_retries"] == 1  # factory override honored

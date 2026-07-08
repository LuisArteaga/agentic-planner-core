import os
import tempfile
import pytest
import yaml
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
    yield
    # Restore original environment
    os.environ.clear()
    os.environ.update(old_env)


def create_temp_yaml(data):
    temp = tempfile.NamedTemporaryFile(
        delete=False, suffix=".yaml", mode="w", encoding="utf-8"
    )
    yaml.dump(data, temp)
    temp.close()
    return temp.name


def test_missing_env_vars(clean_env):
    temp_file = create_temp_yaml({"strict": False})
    with pytest.raises(ValueError) as exc:
        AppConfig(sources_yaml_path=temp_file)
    assert "Missing required environment variable(s)" in str(exc.value)
    os.unlink(temp_file)


def test_valid_config(clean_env):
    os.environ["OPENROUTER_API_KEY"] = "test-key"
    os.environ["GH_PAT"] = "test-pat"
    os.environ["GITHUB_REPOSITORY"] = "test/repo"

    yaml_data = {
        "strict": True,
        "urls": ["https://github.com/test/repo-allowed"],
        "domains": ["example.com"],
    }
    temp_file = create_temp_yaml(yaml_data)

    config = AppConfig(sources_yaml_path=temp_file)
    assert config.openrouter_api_key == "test-key"
    assert config.sources.strict is True
    assert "https://github.com/test/repo-allowed" in config.sources.urls
    assert "example.com" in config.sources.domains

    os.unlink(temp_file)


def test_strict_mode_without_sources(clean_env):
    os.environ["OPENROUTER_API_KEY"] = "test-key"
    os.environ["GH_PAT"] = "test-pat"
    os.environ["GITHUB_REPOSITORY"] = "test/repo"

    yaml_data = {"strict": True, "urls": [], "domains": []}
    temp_file = create_temp_yaml(yaml_data)

    with pytest.raises(ValueError) as exc:
        AppConfig(sources_yaml_path=temp_file)
    assert "At least one source must be defined" in str(exc.value)

    os.unlink(temp_file)


def test_github_workspace_resolution(clean_env):
    os.environ["OPENROUTER_API_KEY"] = "test-key"
    os.environ["GH_PAT"] = "test-pat"
    os.environ["GITHUB_REPOSITORY"] = "test/repo"

    yaml_data = {"strict": False}
    temp_file = create_temp_yaml(yaml_data)

    # 1. Test relative path resolution
    os.environ["GITHUB_WORKSPACE"] = "sub/dir"
    config = AppConfig(sources_yaml_path=temp_file)
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
        config = AppConfig(sources_yaml_path=temp_file)
        assert config.github_workspace == str(Path(tmpdir).resolve())
        assert os.environ["GITHUB_WORKSPACE"] == config.github_workspace

    # 3. Test default fallback when unset
    if "GITHUB_WORKSPACE" in os.environ:
        del os.environ["GITHUB_WORKSPACE"]
    config = AppConfig(sources_yaml_path=temp_file)
    assert config.github_workspace == os.getcwd()
    assert os.environ["GITHUB_WORKSPACE"] == os.getcwd()

    # 4. Test path traversal prevention for relative GITHUB_WORKSPACE
    os.environ["GITHUB_WORKSPACE"] = "../../../etc"
    with pytest.raises(ValueError) as exc:
        AppConfig(sources_yaml_path=temp_file)
    assert "Path traversal detected" in str(exc.value)

    os.unlink(temp_file)


def test_factory_config_invalid_json(clean_env):
    os.environ["OPENROUTER_API_KEY"] = "test-key"
    os.environ["GH_PAT"] = "test-pat"
    os.environ["GITHUB_REPOSITORY"] = "test/repo"

    sources_temp = create_temp_yaml({"strict": False})
    # Create invalid json file
    temp_json = tempfile.NamedTemporaryFile(
        delete=False, suffix=".json", mode="w", encoding="utf-8"
    )
    temp_json.write("{invalid json: }")
    temp_json.close()

    with pytest.raises(ValueError) as exc:
        AppConfig(sources_yaml_path=sources_temp, factory_json_path=temp_json.name)
    assert "Invalid JSON format" in str(exc.value)

    os.unlink(sources_temp)
    os.unlink(temp_json.name)


def test_factory_config_missing_file(clean_env):
    os.environ["OPENROUTER_API_KEY"] = "test-key"
    os.environ["GH_PAT"] = "test-pat"
    os.environ["GITHUB_REPOSITORY"] = "test/repo"

    sources_temp = create_temp_yaml({"strict": False})

    with pytest.raises(FileNotFoundError) as exc:
        AppConfig(
            sources_yaml_path=sources_temp, factory_json_path="nonexistent_factory.json"
        )
    assert "Factory configuration file not found" in str(exc.value)

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

    sources_temp = create_temp_yaml({"strict": False})
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
    config = AppConfig(sources_yaml_path=sources_temp, factory_json_path=temp_json.name)
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
        }

        # Mock ChatOpenAI to avoid real network/package instantiation overhead
        with patch("planner.config.ChatOpenAI") as mock_chat_openai:
            mock_chat_openai.return_value = MagicMock()

            client = get_llm("draft")
            assert client is not None

            mock_chat_openai.assert_called_once()
            called_kwargs = mock_chat_openai.call_args[1]
            assert called_kwargs["model"] == "deepseek/deepseek-v4-pro"
            assert called_kwargs["temperature"] == 0.2
            assert called_kwargs["openai_api_base"] == "https://openrouter.ai/api/v1"
            assert called_kwargs["openai_api_key"] == "test-key"
            assert called_kwargs["use_responses_api"] is False
            assert called_kwargs["timeout"] == 600.0

            # Verify provider routing and thinking options are correctly mapped to extra_body
            extra_body = called_kwargs["model_kwargs"]["extra_body"]
            assert extra_body["provider"] == {
                "order": ["together", "novita"],
                "allow_fallbacks": False,
            }
            assert extra_body["thinking"] == "max"


def test_search_config_parsing_and_overlap(clean_env, caplog):
    os.environ["OPENROUTER_API_KEY"] = "test-key"
    os.environ["GH_PAT"] = "test-pat"
    os.environ["GITHUB_REPOSITORY"] = "test/repo"

    # 1. Test standard parsing of search config
    yaml_data = {
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
    temp_file = create_temp_yaml(yaml_data)
    config = AppConfig(sources_yaml_path=temp_file)

    assert config.sources.search.engine == "exa"
    assert config.sources.search.search_context_size == "medium"
    assert config.sources.search.max_results == 5
    assert config.sources.search.max_total_results == 15
    # Normalization check (lowercase and strip)
    assert "reddit.com" in config.sources.search.excluded_domains
    assert "stackoverflow.com" in config.sources.search.excluded_domains

    os.unlink(temp_file)

    # 2. Test overlap detection and warning logging
    yaml_data_overlap = {
        "strict": True,
        "urls": ["https://github.com/test/repo-allowed"],
        "domains": ["example.com"],
        "search": {
            "engine": "auto",
            "excluded_domains": ["EXAMPLE.COM"],  # Overlaps with domains
        },
    }
    temp_file_overlap = create_temp_yaml(yaml_data_overlap)

    import logging

    with caplog.at_level(logging.WARNING):
        # Trigger validation overlap warning
        AppConfig(sources_yaml_path=temp_file_overlap)

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

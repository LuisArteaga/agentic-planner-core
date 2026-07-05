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
        "repositories": ["test/repo-allowed"],
        "domains": ["example.com"],
    }
    temp_file = create_temp_yaml(yaml_data)

    config = AppConfig(sources_yaml_path=temp_file)
    assert config.openrouter_api_key == "test-key"
    assert config.sources.strict is True
    assert "test/repo-allowed" in config.sources.repositories
    assert "example.com" in config.sources.domains

    os.unlink(temp_file)


def test_strict_mode_without_sources(clean_env):
    os.environ["OPENROUTER_API_KEY"] = "test-key"
    os.environ["GH_PAT"] = "test-pat"
    os.environ["GITHUB_REPOSITORY"] = "test/repo"

    yaml_data = {"strict": True, "repositories": [], "domains": []}
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

    os.unlink(temp_file)

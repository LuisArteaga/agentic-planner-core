import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True, scope="session")
def disable_dotenv_load():
    """Deaktiviert das automatische Laden der echten .env-Datei während der Tests."""
    with patch("planner.config.load_env_file") as mock_load:
        mock_load.return_value = None
        yield

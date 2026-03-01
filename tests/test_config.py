"""Unit tests for configuration."""
import os
import pytest
from pydantic import ValidationError


def test_default_config():
    """Test default configuration loads."""
    # Need to clear env var set by conftest
    if "DATABASE__PATH" in os.environ:
        del os.environ["DATABASE__PATH"]
    
    # Re-import to get fresh settings
    from importlib import reload
    import app.config
    reload(app.config)
    
    from app.config import Settings
    s = Settings()
    
    # Default should be chatbotura.db
    assert s.chroma.path == "chroma_data"
    assert s.api.host == "0.0.0.0"
    assert s.api.port == 8000
    assert s.rate_limit.requests == 100


def test_env_override_database():
    """Test database path can be overridden via env."""
    os.environ["DATABASE__PATH"] = "custom.db"
    
    # Re-import to pick up new env
    from importlib import reload
    import app.config
    reload(app.config)
    
    from app.config import Settings
    s = Settings()
    assert s.database.path == "custom.db"
    
    # Cleanup
    del os.environ["DATABASE__PATH"]


def test_nested_env_override():
    """Test nested configuration via env vars."""
    os.environ["API__HOST"] = "127.0.0.1"
    os.environ["API__PORT"] = "9000"
    
    from importlib import reload
    import app.config
    reload(app.config)
    
    from app.config import Settings
    s = Settings()
    assert s.api.host == "127.0.0.1"
    assert s.api.port == 9000
    
    # Cleanup
    del os.environ["API__HOST"]
    del os.environ["API__PORT"]


def test_llm_config_defaults():
    """Test LLM configuration defaults."""
    from app.config import settings
    
    assert settings.llm.provider == "openai"
    assert settings.llm.openai_model == "gpt-4o"
    assert settings.llm.openrouter_model == "openai/gpt-4o"


def test_cors_origins_default():
    """Test CORS origins default."""
    from app.config import settings
    
    assert "*" in settings.api.cors_origins

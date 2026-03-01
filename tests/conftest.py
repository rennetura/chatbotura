"""Pytest configuration and fixtures for ChatBotura tests."""
import os
import sys
import pytest

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set test environment variables before importing app
os.environ["ADMIN__API_KEY"] = "test-admin-key-123"
os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["LLM_PROVIDER"] = "openai"
os.environ["DATABASE__PATH"] = "chatbotura_test.db"


@pytest.fixture(autouse=True)
def mock_dependencies(monkeypatch):
    """Mock external dependencies that require real setup."""
    # Mock init_rag to avoid ChromaDB initialization
    def mock_init_rag():
        pass
    
    # Mock init_engine to avoid LLM initialization  
    def mock_init_engine():
        pass
    
    # Mock init_db to use test database
    from app import db as db_module
    monkeypatch.setattr(db_module, "init_db", lambda: None)
    
    # Apply mocks before importing main
    import app.rag as rag_module
    import app.engine as engine_module
    monkeypatch.setattr(rag_module, "init_rag", mock_init_rag)
    monkeypatch.setattr(engine_module, "init_engine", mock_init_engine)


@pytest.fixture
def client(mock_dependencies):
    """Create a test client for the FastAPI app."""
    from fastapi.testclient import TestClient
    from main import app
    
    # Create client without running lifespan
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def admin_headers():
    """Headers with admin API key."""
    return {"x-admin-key": "test-admin-key-123"}


@pytest.fixture
def test_tenant_headers():
    """Headers with test tenant API key."""
    return {"x-api-key": "test-tenant-key"}

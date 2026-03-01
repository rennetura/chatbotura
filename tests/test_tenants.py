"""Unit tests for tenant management API."""
import pytest
from unittest.mock import patch, MagicMock


class TestTenantAPI:
    """Tests for tenant management endpoints."""

    def test_create_tenant_requires_admin(self, client):
        """Test that creating tenant requires admin key."""
        response = client.post(
            "/api/v1/admin/tenants",
            json={
                "tenant_id": "new_tenant",
                "business_name": "New Business",
                "system_prompt": "You are helpful.",
                "tone": "friendly"
            }
        )
        assert response.status_code == 401

    def test_create_tenant_invalid_admin_key(self, client):
        """Test that invalid admin key is rejected."""
        response = client.post(
            "/api/v1/admin/tenants",
            headers={"x-admin-key": "wrong-key"},
            json={
                "tenant_id": "new_tenant",
                "business_name": "New Business",
                "system_prompt": "You are helpful.",
                "tone": "friendly"
            }
        )
        assert response.status_code == 403

    def test_list_tenants_requires_admin(self, client):
        """Test that listing tenants requires admin key."""
        response = client.get("/api/v1/admin/tenants")
        assert response.status_code == 401

    def test_get_tenant_requires_admin(self, client):
        """Test that getting tenant requires admin key."""
        response = client.get("/api/v1/admin/tenants/test_tenant")
        assert response.status_code == 401

    def test_update_tenant_requires_admin(self, client):
        """Test that updating tenant requires admin key."""
        response = client.put(
            "/api/v1/admin/tenants/test_tenant",
            json={"business_name": "Updated Name"}
        )
        assert response.status_code == 401

    def test_delete_tenant_requires_admin(self, client):
        """Test that deleting tenant requires admin key."""
        response = client.delete("/api/v1/admin/tenants/test_tenant")
        assert response.status_code == 401

    @patch('main.create_tenant')
    def test_create_tenant_success(self, mock_create, client, admin_headers):
        """Test successful tenant creation."""
        mock_create.return_value = {
            "tenant_id": "new_tenant",
            "business_name": "New Business",
            "system_prompt": "You are helpful.",
            "tone": "friendly",
            "api_key": "test-api-key-123"
        }
        
        response = client.post(
            "/api/v1/admin/tenants",
            headers=admin_headers,
            json={
                "tenant_id": "new_tenant",
                "business_name": "New Business",
                "system_prompt": "You are helpful.",
                "tone": "friendly"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["tenant_id"] == "new_tenant"
        assert "api_key" in data

    @patch('main.create_tenant')
    def test_create_tenant_duplicate(self, mock_create, client, admin_headers):
        """Test creating duplicate tenant returns 409."""
        mock_create.return_value = None  # Simulates existing tenant
        
        response = client.post(
            "/api/v1/admin/tenants",
            headers=admin_headers,
            json={
                "tenant_id": "existing_tenant",
                "business_name": "Existing",
                "system_prompt": "You are helpful.",
                "tone": "friendly"
            }
        )
        
        assert response.status_code == 409


class TestTenantValidation:
    """Tests for tenant request validation."""

    def test_create_tenant_invalid_tenant_id(self, client, admin_headers):
        """Test validation of tenant_id format."""
        response = client.post(
            "/api/v1/admin/tenants",
            headers=admin_headers,
            json={
                "tenant_id": "Invalid-ID!",  # Invalid characters
                "business_name": "Test",
                "system_prompt": "You are helpful.",
                "tone": "friendly"
            }
        )
        assert response.status_code == 422  # Validation error

    def test_create_tenant_invalid_tone(self, client, admin_headers):
        """Test validation of tone field."""
        response = client.post(
            "/api/v1/admin/tenants",
            headers=admin_headers,
            json={
                "tenant_id": "valid_id",
                "business_name": "Test",
                "system_prompt": "You are helpful.",
                "tone": "invalid_tone"
            }
        )
        assert response.status_code == 422  # Validation error

    def test_create_tenant_short_system_prompt(self, client, admin_headers):
        """Test validation of minimum system prompt length."""
        response = client.post(
            "/api/v1/admin/tenants",
            headers=admin_headers,
            json={
                "tenant_id": "valid_id",
                "business_name": "Test",
                "system_prompt": "Short",  # Too short
                "tone": "friendly"
            }
        )
        assert response.status_code == 422  # Validation error

import os
import tempfile
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

os.environ["AI_WORKBENCH_DB_PATH"] = str(Path(tempfile.gettempdir()) / f"standard-ai-workbench-test-{uuid4()}.db")
os.environ["APP_AUTH_SECRET"] = "test-app-secret"

from backend.main import app


client = TestClient(app)
auth_response = client.post("/api/v1/auth/setup", json={"username": "tester", "password": "test-password"})
assert auth_response.status_code == 200
client.headers.update({"Authorization": f"Bearer {auth_response.json()['token']}", "X-App-Auth-Secret": "test-app-secret"})


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["app"] == "standard-ai-workbench-module"


def test_auth_and_cors_guards():
    bare_client = TestClient(app)
    status = bare_client.get("/api/v1/auth/status")
    assert status.status_code == 200
    assert status.json()["setup_required"] is False
    assert status.json()["existing_username"] == "tester"

    wrong_user = bare_client.post("/api/v1/auth/login", json={"username": "other", "password": "test-password"})
    assert wrong_user.status_code == 401
    assert "本机账号为 tester" in wrong_user.json()["detail"]

    assert bare_client.get("/api/v1/projects").status_code == 403
    assert bare_client.get("/api/v1/projects", headers={"X-App-Auth-Secret": "test-app-secret"}).status_code == 401
    preflight = bare_client.options(
        "/api/v1/me",
        headers={
            "Origin": "app://frontend",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,x-app-auth-secret",
            "Access-Control-Request-Private-Network": "true",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-private-network"] == "true"


def test_project_conversation_message_and_search():
    created_project = client.post("/api/v1/projects", json={"title": "Alpha 项目", "workspace_path": "/tmp/alpha-workspace"})
    assert created_project.status_code == 200
    project_id = created_project.json()["id"]
    assert created_project.json()["workspace_path"] == "/tmp/alpha-workspace"

    created_conversation = client.post("/api/v1/conversations", json={"project_id": project_id, "title": "技术路线讨论"})
    assert created_conversation.status_code == 200
    conversation_id = created_conversation.json()["id"]

    messages = client.get(f"/api/v1/conversations/{conversation_id}/messages")
    assert messages.status_code == 200
    assert messages.json() == []

    search = client.get("/api/v1/search", params={"q": "技术路线"})
    assert search.status_code == 200
    assert any(item["conversation_id"] == conversation_id for item in search.json())

    path_search = client.get("/api/v1/search", params={"q": "alpha-workspace"})
    assert path_search.status_code == 200
    assert any(item["project_id"] == project_id for item in path_search.json())


def test_provider_profile_does_not_echo_api_key():
    created = client.post(
        "/api/v1/provider-profiles",
        json={
            "provider": "OpenAI",
            "display_name": "OpenAI",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o",
            "api_key": "secret",
        },
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload["has_key"] is True
    assert "api_key" not in payload

    listed = client.get("/api/v1/provider-profiles")
    assert listed.status_code == 200
    assert any(profile["id"] == payload["id"] for profile in listed.json())


def test_mcp_env_masking():
    created = client.post(
        "/api/v1/mcp-servers",
        json={"name": "mock", "command": "node", "args": ["server.js"], "env": {"SECRET": "value"}, "enabled": True},
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload["env"] == {"SECRET": "********"}
    assert payload["enabled"] is True

    listed = client.get("/api/v1/mcp-servers")
    assert listed.status_code == 200
    assert any(server["id"] == payload["id"] and server["env"] == {"SECRET": "********"} for server in listed.json())

    disabled = client.patch(f"/api/v1/mcp-servers/{payload['id']}", json={"enabled": False})
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False


def test_example_workflow_contract_and_artifacts():
    skills = client.get("/api/v1/skills")
    assert skills.status_code == 200
    assert skills.json()[0]["skill_name"] == "example_echo_workflow"

    created = client.post("/api/v1/workflows", json={"skill_name": "example_echo_workflow", "input_text": "测试输入"})
    assert created.status_code == 200
    workflow_id = created.json()["id"]

    run = client.post(f"/api/v1/workflows/{workflow_id}/run", json={"input_text": "测试输入"})
    assert run.status_code == 200
    assert run.json()["workflow"]["status"] == "waiting_confirmation"

    confirmed = client.post(f"/api/v1/workflows/{workflow_id}/confirm", json={"text": "确认"})
    assert confirmed.status_code == 200
    assert confirmed.json()["workflow"]["status"] == "completed"

    artifacts = client.get(f"/api/v1/workflows/{workflow_id}/artifacts")
    assert artifacts.status_code == 200
    assert artifacts.json()[0]["name"] == "example_echo_result.md"

    artifact = client.get(f"/api/v1/workflows/{workflow_id}/artifacts/example_echo_result.md")
    assert artifact.status_code == 200
    assert "示例 Echo Workflow 成果" in artifact.text

    archive = client.get(f"/api/v1/workflows/{workflow_id}/export.zip")
    assert archive.status_code == 200
    assert archive.headers["content-type"] == "application/zip"

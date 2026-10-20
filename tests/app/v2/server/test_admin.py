from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.app.v2.server.conftest import register_and_login


def admin_login(client: TestClient) -> str:
    login = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin12345"},
    )
    assert login.status_code == 200
    assert login.json()["data"]["user"]["role"] == "admin"
    return login.json()["data"]["access_token"]


@pytest.mark.timeout(30)
def test_admin_can_see_all_users_threads_and_models(client: TestClient):
    alice = register_and_login(client, "alice")
    run = client.post(
        "/api/agent",
        json={
            "threadId": "thread-alice",
            "runId": "run-alice",
            "messages": [{"id": "m1", "role": "user", "content": "hello"}],
            "forwardedProps": {},
        },
        headers={"Authorization": f"Bearer {alice}"},
    )
    assert run.status_code == 200
    saved = client.post(
        "/api/models",
        json={
            "protocol": "openai-chat-completions",
            "base_url": "https://models.example.com/v1",
            "model": "demo-model",
            "api_key": "sk-test",
        },
        headers={"Authorization": f"Bearer {alice}"},
    )
    assert saved.status_code == 200

    admin = admin_login(client)
    headers = {"Authorization": f"Bearer {admin}"}
    users = client.get("/api/admin/users", headers=headers)
    assert {item["username"] for item in users.json()["data"]} >= {"admin", "alice"}
    threads = client.get("/api/admin/threads", headers=headers)
    assert any(item["thread_id"] == "thread-alice" for item in threads.json()["data"]["items"])
    models = client.get("/api/admin/models", headers=headers)
    assert any(item["model"] == "demo-model" for item in models.json()["data"])
    hidden = client.get("/api/admin/users", headers={"Authorization": f"Bearer {alice}"})
    assert hidden.status_code == 403


def test_only_one_admin_is_bootstrapped(client: TestClient):
    register = client.post(
        "/api/auth/register",
        json={"username": "admin", "password": "secret1"},
    )
    assert register.status_code == 409
    login = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin12345"},
    )
    assert login.json()["data"]["user"]["role"] == "admin"


def test_agent_summaries_include_owner_models_and_enforce_scope(client):
    alice = {"Authorization": f"Bearer {register_and_login(client, 'alice')}"}
    bob = {"Authorization": f"Bearer {register_and_login(client, 'bob')}"}
    model = client.post('/api/models', headers=alice, json={
        'model': 'alice-model', 'api_key': 'private-key',
    }).json()['data']
    agent = client.post('/api/agents', headers=alice, json={
        'name': 'Alice agent', 'model_id': model['id'],
        'instructions': 'Private instructions', 'tools': ['file_read'],
    }).json()['data']
    own = client.get('/api/agents/summary', headers=alice)
    assert own.status_code == 200, own.text
    summary = next(item for item in own.json()['data'] if item['id'] == agent['id'])
    assert summary['model_name'] == 'alice-model'
    assert summary['tool_count'] == 1
    assert summary['skill_count'] == 0
    assert set(summary) == {'id', 'name', 'description', 'model_id', 'model_name', 'tool_count', 'skill_count'}
    assert agent['id'] not in {item['id'] for item in client.get('/api/agents/summary', headers=bob).json()['data']}
    assert client.get('/api/admin/agents', headers=alice).status_code == 403
    admin = {"Authorization": f"Bearer {admin_login(client)}"}
    all_agents = client.get('/api/admin/agents', headers=admin)
    assert all_agents.status_code == 200, all_agents.text
    assert {item['username'] for item in all_agents.json()['data']} == {'admin', 'alice', 'bob'}
    summary = next(item for item in all_agents.json()['data'] if item['id'] == agent['id'])
    assert summary['username'] == 'alice'
    assert summary['model_name'] == 'alice-model'
    assert 'private-key' not in all_agents.text
    assert 'Private instructions' not in all_agents.text


def test_admin_read_scope_covers_user_data_without_changing_identity(client):
    alice = {"Authorization": f"Bearer {register_and_login(client, 'alice')}"}
    bob = {"Authorization": f"Bearer {register_and_login(client, 'bob')}"}
    alice_id = client.get('/api/auth/session', headers=alice).json()['data']['user_id']
    agent = client.post('/api/agents', headers=alice, json={
        'name': 'Alice private agent', 'instructions': 'Only Alice instructions',
    }).json()['data']
    client.post('/api/keys', headers=alice, json={'name': 'private-key'})
    skill = client.post('/api/skills', headers=alice, json={
        'name': 'private-skill', 'content': '---\nname: private-skill\ndescription: private\n---\nPrivate skill body',
    })
    assert skill.status_code == 200, skill.text
    skill_id = skill.json()['data']['skill_id']
    bundle = client.get('/api/agent-packages/template', headers=alice).json()['data']
    saved = client.post('/api/agent-packages', headers=alice, json=bundle)
    assert saved.status_code == 200, saved.text
    package_ref = saved.json()['data']['ref']
    run = client.post('/api/agent', headers=alice, json={
        'threadId': 'alice-private-thread', 'runId': 'alice-run',
        'messages': [{'id': 'm1', 'role': 'user', 'content': 'private hello'}],
    })
    assert run.status_code == 200, run.text
    client.post('/api/models', headers=alice, json={'model': 'private-model', 'api_key': 'secret-model-key'})

    admin = {'Authorization': f'Bearer {admin_login(client)}', 'X-Sage-View-User': alice_id}
    paths = [
        '/api/agents', '/api/agents/summary', f"/api/agents/{agent['id']}", f"/api/agents/{agent['id']}/skills",
        '/api/models', '/api/mcp', '/api/a2a-agents', '/api/keys',
        '/api/skills', f'/api/skills/{skill_id}', '/api/auth/execution-policy',
        '/api/approvals', '/api/threads', '/api/threads/alice-private-thread/events?offset=0&limit=2',
        '/api/agent-packages', f'/api/agent-packages/{package_ref}',
        '/api/agent-packages/runs', '/api/agent-packages/resources',
    ]
    for path in paths:
        expected = client.get(path, headers=alice)
        response = client.get(path, headers=admin)
        assert response.status_code == expected.status_code == 200, (path, response.text)
        assert response.json()['data'] == expected.json()['data'], path
        forbidden = client.get(path, headers={**bob, 'X-Sage-View-User': alice_id})
        assert forbidden.status_code == 403, (path, forbidden.text)
    assert client.get('/api/auth/session', headers=admin).json()['data']['role'] == 'admin'
    assert client.get('/api/models', headers=bob).json()['data'] == []
    assert client.get(f"/api/agents/{agent['id']}", headers=bob).status_code == 404
    assert client.get('/api/threads/alice-private-thread/events', headers=bob).status_code == 404
    assert 'secret-model-key' not in client.get('/api/models', headers=admin).text
    assert 'api_key' not in client.get('/api/keys', headers=admin).json()['data'][0]

    writes = [
        ('post', '/api/agents', {'name': 'must not create'}),
        ('delete', f"/api/agents/{agent['id']}", None),
        ('put', '/api/auth/execution-policy', {}),
        ('post', f'/api/agent-packages/{package_ref}/activate', {}),
    ]
    for method, path, body in writes:
        response = client.request(method, path, headers=admin, json=body)
        assert response.status_code == 403, (path, response.text)
    assert client.get(f"/api/agents/{agent['id']}", headers=alice).status_code == 200
    missing = client.get('/api/models', headers={**admin, 'X-Sage-View-User': 'missing'})
    assert missing.status_code == 404


def test_admin_can_read_foreign_studio_run_and_paginate_events(client):
    from tests.app.v2.server.test_packages import settled

    alice = {'Authorization': f'Bearer {register_and_login(client, "alice")}'}
    owner = client.get('/api/auth/session', headers=alice).json()['data']['user_id']
    bundle = client.get('/api/agent-packages/template', headers=alice).json()['data']
    saved = client.post('/api/agent-packages', headers=alice, json=bundle)
    ref = saved.json()['data']['ref']
    run = client.post('/api/agent-packages/runs', headers=alice, json={
        'ref': ref, 'agent_id': 'assistant', 'content': 'hello', 'operation': 'private-run',
    })
    assert run.status_code == 200, run.text
    settled(client, alice, 'private-run')
    admin = {'Authorization': f'Bearer {admin_login(client)}', 'X-Sage-View-User': owner}
    for path in ['/api/agent-packages/runs', '/api/agent-packages/runs/private-run']:
        response = client.get(path, headers=admin)
        assert response.status_code == 200, response.text
        assert response.json()['data'] == client.get(path, headers=alice).json()['data']
    first = client.get('/api/agent-packages/runs/private-run/events?limit=1', headers=admin).json()['data']
    assert len(first['events']) == 1
    second = client.get(f"/api/agent-packages/runs/private-run/events?limit=1&after_sequence={first['cursor']}", headers=admin).json()['data']
    assert second['cursor'] > first['cursor']
    bob = {'Authorization': f'Bearer {register_and_login(client, "bob")}', 'X-Sage-View-User': owner}
    assert client.get('/api/agent-packages/runs/private-run/events', headers=bob).status_code == 403

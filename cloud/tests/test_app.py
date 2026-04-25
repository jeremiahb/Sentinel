from fastapi.testclient import TestClient

from cloud.app import create_app


def test_healthcheck() -> None:
    app = create_app()
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_intune_webhook_persists_notifications() -> None:
    app = create_app()
    client = TestClient(app)

    payload = {
        "value": [
            {
                "id": "notif-1",
                "resource": "/deviceManagement/deviceConfigurations/abc",
                "targetGroups": ["group-1"],
                "actor": "admin@example.com",
            }
        ]
    }

    response = client.post("/webhook/intune", json=payload)

    assert response.status_code == 202
    saved = app.state.policy_event_store.list()
    assert len(saved) == 1
    assert saved[0].external_id == "notif-1"
    assert saved[0].policy_name == "/deviceManagement/deviceConfigurations/abc"

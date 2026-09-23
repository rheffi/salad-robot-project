from __future__ import annotations

import time

from fastapi.testclient import TestClient

from web_ui.app import create_app


def wait_for_state(client: TestClient, expected: str | set[str], *, timeout: float = 3.0) -> dict:
    expected_states = {expected} if isinstance(expected, str) else expected
    deadline = time.monotonic() + timeout
    latest = client.get("/api/status").json()
    while time.monotonic() < deadline:
        latest = client.get("/api/status").json()
        if latest["state"] in expected_states and not latest["busy"]:
            return latest
        time.sleep(0.01)
    raise AssertionError(f"상태 전이 시간 초과: {latest}")


def initialized_client() -> TestClient:
    return TestClient(create_app(step_delay=0.01))


def test_dashboard_and_initial_status() -> None:
    with initialized_client() as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "Salad Robot Control" in response.text
        status = client.get("/api/status").json()
        assert status["state"] == "OFFLINE"
        assert status["mode"] == "DRY_RUN"
        assert status["live_robot"] is False


def test_full_mock_salad_flow_and_duplicate_lock() -> None:
    with initialized_client() as client:
        response = client.post("/api/initialize")
        assert response.status_code == 202
        assert response.json()["job_id"].startswith("initialize-")
        assert client.post("/api/initialize").status_code == 409
        wait_for_state(client, "READY")

        assert client.post("/api/detect").status_code == 202
        wait_for_state(client, "READY")
        detections = client.get("/api/detections").json()
        assert [item["class_name"] for item in detections] == ["tomato", "cheese", "berry", "bowl"]

        response = client.post("/api/run", json={"dry_run": True, "recipe": {"tomato": 1, "cheese": 1, "berry": 1}})
        assert response.status_code == 202
        assert client.post("/api/home").status_code == 409
        final = wait_for_state(client, "FINISHED")
        assert final["progress"] == 100
        assert all(item["status"] == "완료" for item in client.get("/api/detections").json() if item['class_name'] != 'bowl')
        logs = client.get("/api/logs").json()["items"]
        assert any("Mock 샐러드 작업을 완료" in item["message"] for item in logs)


def test_stop_request_returns_to_ready_and_home_works() -> None:
    with initialized_client() as client:
        client.post("/api/initialize")
        wait_for_state(client, "READY")
        client.post("/api/detect")
        wait_for_state(client, "READY")
        client.post("/api/run", json={"dry_run": True, "recipe": {"tomato": 1}})
        time.sleep(0.02)
        assert client.post("/api/stop").status_code == 200
        assert wait_for_state(client, "READY")["progress"] == 0
        assert client.post("/api/home").status_code == 202
        wait_for_state(client, "READY")


def test_live_robot_request_is_rejected() -> None:
    with initialized_client() as client:
        client.post("/api/initialize")
        wait_for_state(client, "READY")
        client.post("/api/detect")
        wait_for_state(client, "READY")
        response = client.post("/api/run", json={"dry_run": False, "recipe": {}})
        assert response.status_code == 409
        assert "실제 로봇 실행" in response.json()["detail"]


def test_websocket_publishes_status_and_log_events() -> None:
    with initialized_client() as client:
        with client.websocket_connect("/ws/events") as websocket:
            initial = websocket.receive_json()
            assert initial["type"] == "status"
            assert initial["data"]["state"] == "OFFLINE"

            assert client.post("/api/initialize").status_code == 202
            event_types: set[str] = set()
            states: set[str] = set()
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline and not ({"status", "log"} <= event_types):
                event = websocket.receive_json()
                event_types.add(event["type"])
                if event["type"] == "status":
                    states.add(event["data"]["state"])

            assert {"status", "log"} <= event_types
            assert "INITIALIZING" in states

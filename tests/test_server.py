import pytest
from fastapi.testclient import TestClient

from fridge import server
from fridge.errors import AgentFailure

client = TestClient(server.app, base_url="http://127.0.0.1")
PAYLOAD = {"ingredients": ["鸡蛋", "番茄", "白菜"], "people": 2, "minutes": 30, "mode": "demo"}


def test_page_example_and_static_assets():
    response = client.get("/")
    assert response.status_code == 200
    assert "冰箱有招" in response.text
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/static/app.js").status_code == 200
    result = client.post("/api/plan", json=PAYLOAD)
    assert result.status_code == 200
    assert len(result.json()["plan"]["dishes"]) == 2


def test_private_files_not_served():
    for path in ["/.env", "/.git/config", "/content", "/static/../.env", "/examples/dinner.json"]:
        assert client.get(path).status_code == 404


def test_status_never_returns_credentials(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "test-secret-never-return")
    monkeypatch.setenv("MODEL_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("MODEL_ID", "example-model")
    response = client.get("/api/status")
    assert response.json()["model_ready"] is True
    assert "test-secret" not in response.text
    assert "example.invalid" not in response.text


def test_unconfigured_model_is_not_silently_replaced_with_demo(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    result = client.post("/api/plan", json=dict(PAYLOAD, mode="agent"))
    assert result.status_code == 409
    assert "plan" not in result.json()


def test_cross_origin_and_bad_host_are_rejected():
    assert client.post("/api/plan", json=PAYLOAD, headers={"Origin": "https://example.invalid"}).status_code == 403
    assert client.get("/", headers={"Host": "attacker.invalid"}).status_code == 400


def test_agent_errors_are_sanitized_and_lock_released(monkeypatch):
    monkeypatch.setattr("fridge.agent.model_ready", lambda: True)
    def fail(*args):
        raise RuntimeError("test-secret-provider-response")
    monkeypatch.setattr(server, "isolated_agent", fail)
    response = client.post("/api/plan", json=dict(PAYLOAD, mode="agent"))
    assert response.status_code == 502
    assert "test-secret" not in response.text
    assert not server._agent_lock.locked()
    assert response.json()["detail"]["code"] == "unknown"


@pytest.mark.parametrize("code,status", [("model_auth", 502), ("model_rate_limit", 503),
                                         ("model_timeout", 504), ("menu_incomplete", 502),
                                         ("menu_unavailable", 422)])
def test_categorized_agent_errors_reach_page_without_becoming_generic(monkeypatch, code, status):
    monkeypatch.setattr("fridge.agent.model_ready", lambda: True)
    def fail(*args):
        raise AgentFailure(code)
    monkeypatch.setattr(server, "isolated_agent", fail)
    response = client.post("/api/plan", json=dict(PAYLOAD, mode="agent"))
    assert response.status_code == status
    assert response.json()["detail"] == {"message": AgentFailure(code).message, "code": code}
    assert "plan" not in response.json()
    assert not server._agent_lock.locked()


def test_worker_sends_only_safe_error_code(monkeypatch):
    import httpx
    from openai import APIConnectionError
    messages = []
    class Connection:
        closed = False
        def send(self, value):
            messages.append(value)
        def close(self):
            self.closed = True
    def fail(*args):
        raise APIConnectionError(message="secret-provider-body",
                                 request=httpx.Request("POST", "https://private.invalid"))
    monkeypatch.setattr("fridge.agent.run_agent", fail)
    connection = Connection()
    server._worker(dict(PAYLOAD, mode="agent"), connection)
    assert messages == [(False, "model_connection")]
    assert connection.closed


def test_crashed_worker_without_reply_has_safe_error_and_is_joined(monkeypatch):
    class Pipe:
        closed = False
        def poll(self, timeout):
            return True
        def recv(self):
            raise EOFError("private-worker-data")
        def close(self):
            self.closed = True
    class Process:
        closed = False
        joined = False
        def start(self):
            pass
        def join(self, timeout):
            self.joined = True
        def is_alive(self):
            return False
        def close(self):
            self.closed = True
    receiver, sender, process = Pipe(), Pipe(), Process()
    class Context:
        def Pipe(self, duplex):
            return receiver, sender
        def Process(self, **kwargs):
            return process
    monkeypatch.setattr(server.multiprocessing, "get_context", lambda _: Context())
    with pytest.raises(AgentFailure) as error:
        server.isolated_agent(dict(PAYLOAD, mode="agent"))
    assert error.value.code == "worker_stopped"
    assert "private" not in str(error.value)
    assert receiver.closed and sender.closed and process.closed and process.joined


def test_conflicting_time_is_reported():
    assert client.post("/api/plan", json=dict(PAYLOAD, minutes=15)).status_code == 422


def test_timeout_terminates_worker():
    with pytest.raises(TimeoutError):
        server.isolated_agent(dict(PAYLOAD, mode="agent"), timeout=0.001)

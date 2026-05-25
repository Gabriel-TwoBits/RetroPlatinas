import logging

import pytest

from apps.api.handlers import HANDLERS


@pytest.mark.django_db
def test_dorequest_login2_stub(client):
    response = client.post("/dorequest.php", {"r": "login2"})
    data = response.json()
    assert response.status_code == 200
    assert data["Success"] is False
    assert data["Error"] == "not implemented"


@pytest.mark.django_db
def test_dorequest_missing_r(client):
    response = client.post("/dorequest.php", {})
    data = response.json()
    assert response.status_code == 200
    assert data["Success"] is False
    assert "r" in data["Error"]


@pytest.mark.django_db
def test_dorequest_unknown_action(client):
    response = client.post("/dorequest.php", {"r": "banana"})
    data = response.json()
    assert response.status_code == 200
    assert data["Success"] is False
    assert "banana" in data["Error"]


@pytest.mark.django_db
@pytest.mark.parametrize("action", list(HANDLERS.keys()))
def test_all_handlers_stubbed(client, action):
    response = client.post("/dorequest.php", {"r": action})
    data = response.json()
    assert response.status_code == 200
    assert data["Success"] is False
    assert data["Error"] == "not implemented"


@pytest.mark.django_db
def test_get_method_rejected(client):
    response = client.get("/dorequest.php")
    assert response.status_code == 405


@pytest.mark.django_db
def test_middleware_logs_request_without_credentials(client, caplog):
    with caplog.at_level(logging.INFO, logger="apps.api"):
        client.post("/dorequest.php", {"r": "login2", "u": "alice", "p": "secret", "t": "tok"})

    assert any("r=login2" in record.message for record in caplog.records)
    assert any("u=alice" in record.message for record in caplog.records)
    assert not any("secret" in record.message for record in caplog.records)
    assert not any("tok" in record.message for record in caplog.records)

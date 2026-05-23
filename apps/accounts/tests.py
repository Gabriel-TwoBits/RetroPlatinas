import pytest
from django.contrib.auth import get_user_model

from apps.accounts.forms import RegistrationForm

User = get_user_model()


@pytest.mark.django_db
def test_register_creates_user_and_logs_in(client):
    resp = client.post("/register/", {
        "username": "alice",
        "email": "alice@example.com",
        "password1": "very-strong-pw-1",
        "password2": "very-strong-pw-1",
    })
    assert resp.status_code == 302
    assert resp.url == "/"
    assert User.objects.filter(username="alice").exists()
    assert "_auth_user_id" in client.session


@pytest.mark.django_db
def test_register_rejects_duplicate_email():
    User.objects.create_user(username="alice", email="dup@example.com", password="irrelevant")
    form = RegistrationForm(data={
        "username": "bob",
        "email": "dup@example.com",
        "password1": "very-strong-pw-1",
        "password2": "very-strong-pw-1",
    })
    assert not form.is_valid()
    assert "email" in form.errors
    assert not User.objects.filter(username="bob").exists()


@pytest.mark.django_db
def test_login_with_valid_credentials(client):
    User.objects.create_user(username="alice", password="pw-secret-123")
    resp = client.post("/login/", {"username": "alice", "password": "pw-secret-123"})
    assert resp.status_code == 302
    assert "_auth_user_id" in client.session


@pytest.mark.django_db
def test_login_with_wrong_password(client):
    User.objects.create_user(username="alice", password="correct-pw-123")
    resp = client.post("/login/", {"username": "alice", "password": "wrong"})
    assert resp.status_code == 200
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_logout_ends_session(client):
    User.objects.create_user(username="alice", password="pw-secret-123")
    client.login(username="alice", password="pw-secret-123")
    assert "_auth_user_id" in client.session
    client.post("/logout/")
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_homepage_renders_portuguese_by_default(client):
    resp = client.get("/", HTTP_ACCEPT_LANGUAGE="pt")
    assert resp.status_code == 200
    assert "Bem-vindo" in resp.content.decode()


@pytest.mark.django_db
def test_set_language_switches_to_english(client):
    resp = client.post("/i18n/setlang/", {"language": "en", "next": "/"}, follow=True)
    assert resp.status_code == 200
    assert "Welcome to RetroCheevos" in resp.content.decode()

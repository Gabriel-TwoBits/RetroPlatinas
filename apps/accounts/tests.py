import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.accounts.forms import RegistrationForm

User = get_user_model()


@pytest.mark.django_db
def test_register_creates_user_and_logs_in(client):
    resp = client.post(
        "/register/",
        {
            "username": "alice",
            "email": "alice@example.com",
            "password1": "very-strong-pw-1",
            "password2": "very-strong-pw-1",
        },
    )
    assert resp.status_code == 302
    assert resp.url == "/"
    assert User.objects.filter(username="alice").exists()
    assert "_auth_user_id" in client.session


@pytest.mark.django_db
def test_register_rejects_duplicate_email():
    User.objects.create_user(username="alice", email="dup@example.com", password="irrelevant")
    form = RegistrationForm(
        data={
            "username": "bob",
            "email": "dup@example.com",
            "password1": "very-strong-pw-1",
            "password2": "very-strong-pw-1",
        }
    )
    assert not form.is_valid()
    assert "email" in form.errors
    assert not User.objects.filter(username="bob").exists()


@pytest.mark.django_db
def test_register_rejects_email_differing_only_in_case():
    User.objects.create_user(username="alice", email="dup@example.com", password="irrelevant")
    form = RegistrationForm(
        data={
            "username": "bob",
            "email": "DUP@Example.com",
            "password1": "very-strong-pw-1",
            "password2": "very-strong-pw-1",
        }
    )
    assert not form.is_valid()
    assert "email" in form.errors


@pytest.mark.django_db
def test_database_rejects_email_differing_only_in_case():
    User.objects.create_user(username="alice", email="dup@example.com", password="irrelevant")
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create_user(username="bob", email="DUP@example.com", password="irrelevant")


@pytest.mark.django_db
def test_model_validation_rejects_email_differing_only_in_case():
    User.objects.create_user(username="alice", email="dup@example.com", password="irrelevant")
    with pytest.raises(ValidationError):
        User(username="bob", email="Dup@Example.com", password="irrelevant").full_clean()


@pytest.mark.django_db
def test_admin_adds_user_without_email_next_to_another_blank_email(client):
    User.objects.create_user(username="ra-import", is_active=False)
    admin = User.objects.create_superuser(
        username="admin", email="admin@example.com", password="pw-secret-123"
    )
    client.force_login(admin)
    resp = client.post(
        "/admin/accounts/user/add/",
        {
            "username": "newbie",
            "usable_password": "true",
            "password1": "very-strong-pw-1",
            "password2": "very-strong-pw-1",
        },
    )
    assert resp.status_code == 302
    assert User.objects.filter(email="").count() == 2


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
    assert "Ver os jogos" in resp.content.decode()


@pytest.mark.django_db
def test_set_language_switches_to_english(client):
    resp = client.post("/i18n/setlang/", {"language": "en", "next": "/"}, follow=True)
    assert resp.status_code == 200
    assert "See the games" in resp.content.decode()


@pytest.mark.django_db
def test_profile_renders_for_existing_user(client):
    User.objects.create_user(username="teste", password="pw-secret-123")
    resp = client.get("/users/teste/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "teste" in body
    assert "Slime Quest VII" in body  # placeholder data rendered


@pytest.mark.django_db
def test_profile_404_for_missing_user(client):
    resp = client.get("/users/ghost/")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_profile_panel_returns_fragment(client):
    User.objects.create_user(username="teste", password="pw-secret-123")
    resp = client.get("/users/teste/panel/progress/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "<!DOCTYPE" not in body  # HTMX fragment, not the full page
    assert "PlayStation 2" in body  # progression section rendered


@pytest.mark.django_db
def test_profile_panel_rejects_unknown_tab(client):
    User.objects.create_user(username="teste", password="pw-secret-123")
    resp = client.get("/users/teste/panel/bogus/")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_edit_button_only_for_owner(client):
    User.objects.create_user(username="teste", email="teste@example.com", password="pw-secret-123")
    User.objects.create_user(username="other", email="other@example.com", password="pw-secret-123")

    resp = client.get("/users/teste/", HTTP_ACCEPT_LANGUAGE="en")
    assert "Edit profile" not in resp.content.decode()

    client.login(username="other", password="pw-secret-123")
    resp = client.get("/users/teste/", HTTP_ACCEPT_LANGUAGE="en")
    assert "Edit profile" not in resp.content.decode()

    client.login(username="teste", password="pw-secret-123")
    resp = client.get("/users/teste/", HTTP_ACCEPT_LANGUAGE="en")
    assert "Edit profile" in resp.content.decode()


@pytest.mark.django_db
def test_password_change_pages_render_for_a_logged_in_user(client):
    User.objects.create_user(username="alice", password="pw-secret-123")
    client.login(username="alice", password="pw-secret-123")
    assert client.get("/password_change/").status_code == 200
    assert client.get("/password_change/done/").status_code == 200


@pytest.mark.django_db
def test_password_change_redirects_an_anonymous_user_to_login(client):
    resp = client.get("/password_change/")
    assert resp.status_code == 302
    assert resp.url.startswith("/login/")

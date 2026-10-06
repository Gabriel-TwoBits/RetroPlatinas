import re

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor

from apps.accounts.forms import RegistrationForm

User = get_user_model()

BEFORE_EMAIL_CONSTRAINT = [("accounts", "0001_initial")]
WITH_EMAIL_CONSTRAINT = [("accounts", "0002_user_email_case_insensitive_unique")]


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


@pytest.mark.django_db(transaction=True)
def test_email_constraint_migration_names_accounts_differing_only_in_case():
    executor = MigrationExecutor(connection)
    executor.migrate(BEFORE_EMAIL_CONSTRAINT)
    old_user = executor.loader.project_state(BEFORE_EMAIL_CONSTRAINT).apps.get_model(
        "accounts", "User"
    )
    old_user.objects.create(username="bob", email="DUP@example.com")
    old_user.objects.create(username="alice", email="dup@example.com")
    old_user.objects.create(username="carol", email="carol@example.com")
    try:
        executor.loader.build_graph()
        with pytest.raises(RuntimeError, match=r"migrating: alice, bob$"):
            executor.migrate(WITH_EMAIL_CONSTRAINT)
    finally:
        old_user.objects.all().delete()
        executor.loader.build_graph()
        executor.migrate(WITH_EMAIL_CONSTRAINT)


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
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.headers["Content-Language"] == "pt-br"
    assert "Ver os jogos" in resp.content.decode()


@pytest.mark.django_db
def test_homepage_prints_each_portuguese_sentence_once(client):
    body = client.get("/").content.decode()
    assert body.count("Somos novos:") == 1
    assert body.count("Escolha um jogo,") == 1


@pytest.mark.django_db
def test_set_language_switches_to_english(client):
    resp = client.post("/i18n/setlang/", {"language": "en", "next": "/"}, follow=True)
    assert resp.status_code == 200
    assert "See the games" in resp.content.decode()


@pytest.mark.django_db
def test_set_language_switches_back_to_brazilian_portuguese(client):
    client.post("/i18n/setlang/", {"language": "en", "next": "/"})
    resp = client.post("/i18n/setlang/", {"language": "pt-br", "next": "/"}, follow=True)
    assert resp.status_code == 200
    assert "Ver os jogos" in resp.content.decode()


@pytest.mark.django_db
def test_language_selector_offers_brazilian_portuguese_selected(client):
    body = client.get("/").content.decode()
    assert '<option value="pt-br" selected>PT-BR</option>' in body
    assert '<option value="en">EN</option>' in body


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["/register/", "/login/"])
def test_auth_pages_use_django_brazilian_portuguese_catalog(client, path):
    body = client.get(path).content.decode()
    assert "Usuário" in body
    assert "Senha" in body
    assert "Utilizador" not in body
    assert "Palavra-passe" not in body


@pytest.mark.django_db
def test_register_duplicate_username_error_uses_django_brazilian_portuguese_catalog(client):
    User.objects.create_user(username="alice", password="irrelevant")
    resp = client.post(
        "/register/",
        {
            "username": "alice",
            "email": "alice@example.com",
            "password1": "very-strong-pw-1",
            "password2": "very-strong-pw-1",
        },
    )
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "Um usuário com este nome de usuário já existe." in body
    assert "utilizador" not in body.lower()


@pytest.mark.django_db
def test_login_error_uses_django_brazilian_portuguese_catalog(client):
    User.objects.create_user(username="alice", password="correct-pw-123")
    resp = client.post("/login/", {"username": "alice", "password": "wrong"})
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "e senha corretos" in body
    assert "utilizador" not in body.lower()


@pytest.mark.django_db
def test_generic_portuguese_cookie_resolves_to_brazilian_portuguese(client, settings):
    settings.LANGUAGE_CODE = "en"
    client.cookies[settings.LANGUAGE_COOKIE_NAME] = "pt"
    resp = client.get("/login/")
    assert resp.headers["Content-Language"] == "pt-br"
    assert "Usuário" in resp.content.decode()


@pytest.mark.django_db
@pytest.mark.parametrize("accept_language", ["pt", "pt-PT"])
def test_generic_portuguese_accept_language_resolves_to_brazilian_portuguese(
    client, settings, accept_language
):
    settings.LANGUAGE_CODE = "en"
    resp = client.get("/login/", HTTP_ACCEPT_LANGUAGE=accept_language)
    assert resp.headers["Content-Language"] == "pt-br"
    assert "Usuário" in resp.content.decode()


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
@pytest.mark.parametrize("tab", ["wall"])
def test_profile_panel_for_a_hidden_section_is_gone(client, tab):
    User.objects.create_user(username="teste", password="pw-secret-123")
    resp = client.get(f"/users/teste/panel/{tab}/")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_profile_hides_sections_without_a_concept(client):
    User.objects.create_user(username="teste", password="pw-secret-123")
    body = client.get("/users/teste/", HTTP_ACCEPT_LANGUAGE="en").content.decode()
    for hidden in ["Event awards", "User wall", "RetroRatio", "Forum posts", "weighted"]:
        assert hidden not in body


@pytest.mark.django_db
def test_mobile_profile_tabs_put_awards_right_after_overview(client):
    User.objects.create_user(username="teste", password="pw-secret-123")
    body = client.get("/users/teste/").content.decode()
    tabs = re.findall(r"/users/teste/panel/(\w+)/", body)
    assert tabs == ["overview", "awards", "games", "progress"]


@pytest.mark.django_db
def test_awards_panel_lists_platinums_first(client):
    User.objects.create_user(username="teste", password="pw-secret-123")
    body = client.get("/users/teste/panel/awards/").content.decode()
    tones = re.findall(r'class="text-(state-platinum|gold) rp-hatch', body)
    first_gold = tones.index("gold")
    assert "state-platinum" in tones
    assert "state-platinum" not in tones[first_gold:]


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

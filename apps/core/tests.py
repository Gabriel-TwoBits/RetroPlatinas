import re

import pytest
from django.contrib.auth import get_user_model

User = get_user_model()

GETTING_STARTED = "/docs/getting-started/"
NAV_LINKS = ["/games/", "/ranking/", "/feed/", GETTING_STARTED]
LANGUAGES = [("pt-br", "Como começar"), ("en", "How to start")]


@pytest.fixture
def player(db):
    return User.objects.create_user(username="teste", password="pw-secret-123")


def _header(body):
    return body[body.index("<header") : body.index("</header>")]


def _mobile_menu(body):
    match = re.search(r'<details id="site-menu".*?</details>', body, re.DOTALL)
    assert match, "mobile menu missing"
    return match.group(0)


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["/", GETTING_STARTED, "/login/", "/register/", "/users/teste/"])
@pytest.mark.parametrize(("language", "nav_label"), LANGUAGES)
def test_public_pages_render_in_each_language(client, player, path, language, nav_label):
    resp = client.get(path, HTTP_ACCEPT_LANGUAGE=language)
    assert resp.status_code == 200
    assert resp.headers["Content-Language"] == language
    assert nav_label in _header(resp.content.decode())


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["/password_change/", "/password_change/done/"])
@pytest.mark.parametrize(("language", "nav_label"), LANGUAGES)
def test_account_pages_render_in_each_language(client, player, path, language, nav_label):
    client.force_login(player)
    resp = client.get(path, HTTP_ACCEPT_LANGUAGE=language)
    assert resp.status_code == 200
    assert resp.headers["Content-Language"] == language
    assert nav_label in _header(resp.content.decode())


@pytest.mark.django_db
@pytest.mark.parametrize("href", NAV_LINKS)
def test_nav_links_present_on_desktop_and_mobile(client, href):
    body = client.get("/").content.decode()
    header = _header(body)
    menu = _mobile_menu(body)
    assert f'href="{href}"' in menu
    assert f'href="{href}"' in header.replace(menu, "")


@pytest.mark.django_db
def test_mobile_menu_holds_the_account_links_and_language_switch(client):
    menu = _mobile_menu(client.get("/").content.decode())
    assert 'href="/login/"' in menu
    assert 'href="/register/"' in menu
    assert 'name="language"' in menu


@pytest.mark.django_db
def test_getting_started_shows_this_server_as_the_cheevos_host(client):
    body = client.get(GETTING_STARTED, HTTP_ACCEPT_LANGUAGE="en").content.decode()
    assert "[Cheevos]\nHost = http://testserver</pre>" in body
    assert "Hardcore mode" in body


@pytest.mark.django_db
def test_getting_started_links_registration_for_an_anonymous_visitor(client):
    body = client.get(GETTING_STARTED, HTTP_ACCEPT_LANGUAGE="en").content.decode()
    article = body[body.index("<article") :]
    assert 'href="/register/"' in article
    assert "already logged in" not in article


@pytest.mark.django_db
def test_getting_started_skips_registration_for_a_logged_in_user(client, player):
    client.force_login(player)
    body = client.get(GETTING_STARTED, HTTP_ACCEPT_LANGUAGE="en").content.decode()
    article = body[body.index("<article") :]
    assert "You're already logged in as teste." in article
    assert 'href="/register/"' not in article


@pytest.mark.django_db
def test_getting_started_is_translated_to_brazilian_portuguese(client):
    body = client.get(GETTING_STARTED).content.decode()
    assert "Crie uma conta" in body
    assert "Modo hardcore" in body


@pytest.mark.django_db
def test_home_links_the_getting_started_guide_from_its_block(client):
    body = client.get("/", HTTP_ACCEPT_LANGUAGE="en").content.decode()
    main = body[body.index("<main") : body.index("</main>")]
    assert f'href="{GETTING_STARTED}"' in main
    assert "Step-by-step guide" in main


@pytest.mark.django_db
def test_home_hides_sections_without_a_concept(client):
    body = client.get("/", HTTP_ACCEPT_LANGUAGE="en").content.decode()
    assert "Suggest the next game" not in body
    assert ">NEW<" not in body

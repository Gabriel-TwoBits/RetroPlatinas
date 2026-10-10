"""The /docs/ pages: every page in both languages, the docs navigation and the FAQ's discs."""

import html
import re

import pytest
from django.contrib.auth import get_user_model

from apps.core.docs import DOC_PAGES
from apps.games.models import Console, Game, GameHash

User = get_user_model()

DOCS = "/docs/"
PAGE_PATHS = [f"/docs/{page.slug}/" for page in DOC_PAGES]
MIN_DOC_PAGES = 5
FAQ = "/docs/faq/"
PLAYSTATION_RA_ID = 12
# Each page's title in English and in Brazilian Portuguese.
TITLES = {
    DOCS: ("Documentation", "Documentação"),
    "/docs/getting-started/": ("How to start playing", "Como começar a jogar"),
    "/docs/creating-achievements/": ("Creating achievements", "Criando conquistas"),
    "/docs/statuses-and-contributing/": (
        "Statuses, sets and contributing",
        "Status, sets e como contribuir",
    ),
    "/docs/leaderboards-and-rich-presence/": (
        "Leaderboards and rich presence",
        "Placares e rich presence",
    ),
    FAQ: ("Frequently asked questions", "Perguntas frequentes"),
}
CRASH_MD5 = "35386fd0891e594c9b6d8a4a5baa0027"
CRASH_LABEL = "Crash Bandicoot (USA) — SCUS-94900"
RA_CONDITION_SYNTAX = "https://docs.retroachievements.org/developer-docs/condition-syntax.html"


def _h1(body):
    match = re.search(r"<h1[^>]*>(.*?)</h1>", body, re.DOTALL)
    assert match, "page title missing"
    return match.group(1).strip()


def _docs_nav(body):
    match = re.search(r'<nav id="docs-nav".*?</nav>', body, re.DOTALL)
    assert match, "docs navigation missing"
    return match.group(0)


def _article(body):
    return body[body.index("<article") : body.index("</article>")]


@pytest.fixture
def crash_disc(db):
    console = Console.objects.create(ra_id=PLAYSTATION_RA_ID, name="PlayStation", short_name="PS1")
    game = Game.objects.create(title="Crash Bandicoot", console=console)
    return GameHash.objects.create(game=game, md5=CRASH_MD5, label=CRASH_LABEL)


def test_docs_have_at_least_five_pages():
    assert len(DOC_PAGES) >= MIN_DOC_PAGES


@pytest.mark.django_db
@pytest.mark.parametrize("path", TITLES)
@pytest.mark.parametrize(("language", "title_index"), [("en", 0), ("pt-br", 1)])
def test_each_docs_page_renders_in_each_language(client, path, language, title_index):
    resp = client.get(path, HTTP_ACCEPT_LANGUAGE=language)
    assert resp.status_code == 200
    assert resp.headers["Content-Language"] == language
    assert _h1(resp.content.decode()) == TITLES[path][title_index]


@pytest.mark.django_db
@pytest.mark.parametrize("path", TITLES)
def test_each_docs_page_links_every_page_from_its_navigation(client, path):
    nav = _docs_nav(client.get(path, HTTP_ACCEPT_LANGUAGE="en").content.decode())
    assert f'href="{DOCS}"' in nav
    for page_path in PAGE_PATHS:
        assert f'href="{page_path}"' in nav


@pytest.mark.django_db
@pytest.mark.parametrize("path", PAGE_PATHS)
def test_docs_navigation_marks_only_the_current_page(client, path):
    nav = _docs_nav(client.get(path, HTTP_ACCEPT_LANGUAGE="en").content.decode())
    current = re.findall(r'<a href="([^"]+)"[^>]*aria-current="page"', nav)
    assert current == [path]


@pytest.mark.django_db
def test_docs_index_marks_itself_current_and_lists_every_page_with_its_summary(client):
    body = client.get(DOCS, HTTP_ACCEPT_LANGUAGE="en").content.decode()
    current = re.findall(r'<a href="([^"]+)"[^>]*aria-current="page"', _docs_nav(body))
    assert current == [DOCS]
    article = _article(body)
    for page in DOC_PAGES:
        assert f'href="/docs/{page.slug}/"' in article
        assert str(page.summary) in article


@pytest.mark.django_db
def test_unknown_docs_page_is_not_found(client):
    assert client.get("/docs/no-such-page/").status_code == 404


@pytest.mark.django_db
@pytest.mark.parametrize("path", [DOCS, FAQ])
def test_docs_pages_refuse_a_post(client, path):
    assert client.post(path).status_code == 405


@pytest.mark.django_db
def test_footer_links_the_docs(client):
    body = client.get("/", HTTP_ACCEPT_LANGUAGE="en").content.decode()
    footer = body[body.index("<footer") : body.index("</footer>")]
    assert f'href="{DOCS}"' in footer
    assert ">Docs</a>" in footer


@pytest.mark.django_db
def test_faq_lists_every_registered_disc(client, crash_disc):
    article = _article(client.get(FAQ, HTTP_ACCEPT_LANGUAGE="en").content.decode())
    assert CRASH_LABEL in article
    assert CRASH_MD5 in article
    assert f'href="/games/{crash_disc.game_id}/"' in article
    assert "No disc registered yet" not in article


@pytest.mark.django_db
def test_faq_says_so_when_no_disc_is_registered(client):
    article = _article(client.get(FAQ, HTTP_ACCEPT_LANGUAGE="en").content.decode())
    assert "No disc registered yet" in article


@pytest.mark.django_db
def test_creating_achievements_points_to_the_retroachievements_developer_docs(client):
    article = _article(
        client.get("/docs/creating-achievements/", HTTP_ACCEPT_LANGUAGE="en").content.decode()
    )
    assert f'href="{RA_CONDITION_SYNTAX}"' in article
    assert "Test Unofficial Achievements" in article
    assert "0xH61998=1_d0xH61998=0" in article


@pytest.mark.django_db
def test_statuses_page_shows_the_site_status_chips_in_brazilian_portuguese(client):
    article = _article(
        client.get(
            "/docs/statuses-and-contributing/", HTTP_ACCEPT_LANGUAGE="pt-br"
        ).content.decode()
    )
    for label in ("Oficial", "Não oficial"):
        assert f"{label}</span>" in article


def _meta_description(body):
    match = re.search(r'<meta name="description" content="([^"]*)">', body)
    assert match, "meta description missing"
    return html.unescape(match.group(1))


@pytest.mark.django_db
@pytest.mark.parametrize("page", DOC_PAGES, ids=lambda page: page.slug)
def test_each_docs_page_describes_itself_with_its_summary(client, page):
    body = client.get(f"/docs/{page.slug}/", HTTP_ACCEPT_LANGUAGE="en").content.decode()
    assert _meta_description(body) == str(page.summary)


@pytest.mark.django_db
def test_docs_index_describes_the_core_set_and_subsets(client):
    body = client.get(DOCS, HTTP_ACCEPT_LANGUAGE="en").content.decode()
    assert "the core set holds a game's normal 100%" in _meta_description(body)


@pytest.mark.django_db
def test_creating_achievements_says_what_belongs_in_each_set(client):
    article = _article(
        client.get("/docs/creating-achievements/", HTTP_ACCEPT_LANGUAGE="en").content.decode()
    )
    for set_name in (
        "Core set",
        "Bonus subset",
        "Challenge subset",
        "Specialty subset",
        "Exclusive subset",
    ):
        assert f">{set_name}</dt>" in article
    assert "If they would not, the achievement belongs in a subset." in article
    assert "Staff add subsets." in article


@pytest.mark.django_db
def test_creating_achievements_set_guidance_is_in_brazilian_portuguese(client):
    article = _article(
        client.get("/docs/creating-achievements/", HTTP_ACCEPT_LANGUAGE="pt-br").content.decode()
    )
    for set_name in (
        "Set principal",
        "Subset bônus",
        "Subset de desafio",
        "Subset especial",
        "Subset exclusivo",
    ):
        assert f">{set_name}</dt>" in article
    assert "O 100% normal do jogo" in article


@pytest.mark.django_db
def test_getting_started_explains_the_core_set_and_the_subset_opt_in(client):
    article = _article(
        client.get("/docs/getting-started/", HTTP_ACCEPT_LANGUAGE="en").content.decode()
    )
    assert "Core set and subsets" in article
    assert "core set is its normal 100%" in article
    assert "turn on Play this subset" in article


@pytest.mark.django_db
def test_statuses_page_explains_the_sets_and_the_platinum(client):
    article = _article(
        client.get("/docs/statuses-and-contributing/", HTTP_ACCEPT_LANGUAGE="en").content.decode()
    )
    assert "A game has one core set, its normal 100%" in article
    assert "A bonus or challenge subset is opt-in" in article
    assert "Points from every set count on profiles and in the ranking." in article
    assert 'href="/docs/creating-achievements/"' in article


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("language", "questions"),
    [
        ("en", ("What is a subset?", "How do I play a subset?", "What counts for the platinum?")),
        ("pt-br", ("O que é um subset?", "Como jogar um subset?", "O que conta para o platinado?")),
    ],
)
def test_faq_answers_subsets_opting_in_and_the_platinum(client, language, questions):
    article = _article(client.get(FAQ, HTTP_ACCEPT_LANGUAGE=language).content.decode())
    for question in questions:
        assert question in article


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("language", "heading", "reason"),
    [
        (
            "en",
            "Why did an achievement not unlock?",
            "It belongs to a bonus or challenge subset you have not turned on",
        ),
        (
            "pt-br",
            "Por que uma conquista não desbloqueou?",
            "Ela é de um subset bônus ou de desafio que você não ligou",
        ),
    ],
)
def test_faq_names_a_subset_left_off_as_a_reason_an_achievement_did_not_unlock(
    client, language, heading, reason
):
    article = _article(client.get(FAQ, HTTP_ACCEPT_LANGUAGE=language).content.decode())
    start = article.index(heading)
    reasons = article[start : article.index("</ul>", start)]
    assert reason in reasons

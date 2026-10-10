"""Subsets as games: the rules a core game and its subsets keep, their admin, the players'
preferences, and the site listings that hold core games only."""

from http import HTTPStatus

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from apps.achievements.models import Achievement, CodeNote, UserUnlock
from apps.core import stats
from apps.games.models import (
    MD5_HEX_DIGITS,
    SET_TYPE_BONUS,
    SET_TYPE_CHALLENGE,
    SET_TYPE_EXCLUSIVE,
    SET_TYPE_SPECIALTY,
    Console,
    Game,
    GameHash,
    PlayerGame,
    UserSetPreference,
)

User = get_user_model()

PLAYSTATION_RA_ID = 12
SATURN_RA_ID = 39
CORE_TITLE = "Crash Bandicoot"
BONUS_TITLE = "Crash Bandicoot [Subset - Bonus]"
MD5 = "c" * MD5_HEX_DIGITS
PASSWORD = "pw-secret-123"
POINTS = 10


@pytest.fixture
def console(db):
    return Console.objects.create(ra_id=PLAYSTATION_RA_ID, name="PlayStation", short_name="PS1")


@pytest.fixture
def core(console):
    return Game.objects.create(title=CORE_TITLE, console=console)


def _subset(core, set_type=SET_TYPE_BONUS, title=BONUS_TITLE, set_title="Bonus"):
    return Game.objects.create(
        title=title,
        console=core.console,
        parent_game=core,
        set_type=set_type,
        set_title=set_title,
    )


@pytest.fixture
def bonus(core):
    return _subset(core)


@pytest.fixture
def player(db):
    return User.objects.create_user(username="player", password=PASSWORD)


@pytest.fixture
def admin_user(db):
    return User.objects.create_superuser(
        username="admin", email="admin@example.com", password=PASSWORD
    )


def _official(game, author):
    return Achievement.objects.create(
        game=game,
        author=author,
        title=f"{game.title} one",
        description="d",
        points=POINTS,
        mem_addr="0xH0001=1",
        status=Achievement.STATUS_OFFICIAL,
    )


# --- The database constraint ---


@pytest.mark.django_db
@pytest.mark.parametrize(
    "fields",
    [
        {"set_type": SET_TYPE_BONUS, "set_title": "Bonus"},
        {"set_title": "Bonus", "with_parent": True},
        {"set_type": SET_TYPE_BONUS, "with_parent": True},
        {"set_type": "speedrun", "set_title": "Speedrun", "with_parent": True},
    ],
    ids=["subset-without-parent", "parent-without-type", "untitled-subset", "unknown-type"],
)
def test_the_database_keeps_core_games_and_titled_subsets_apart(core, fields):
    fields = dict(fields)
    parent = core if fields.pop("with_parent", False) else None
    with pytest.raises(IntegrityError), transaction.atomic():
        Game.objects.create(title=BONUS_TITLE, console=core.console, parent_game=parent, **fields)


@pytest.mark.django_db
def test_a_core_game_and_its_subset_are_valid(core, bonus):
    core.full_clean()
    bonus.full_clean()
    assert core.core_game == core
    assert bonus.core_game == core
    assert list(Game.objects.core()) == [core]


# --- Model validation ---


def _errors(game):
    with pytest.raises(ValidationError) as raised:
        game.full_clean()
    return raised.value.message_dict


@pytest.mark.django_db
def test_a_subset_needs_a_parent_and_a_parent_needs_a_type(core):
    orphan = Game(title=BONUS_TITLE, console=core.console, set_type=SET_TYPE_BONUS, set_title="B")
    untyped = Game(title=BONUS_TITLE, console=core.console, parent_game=core)

    assert "parent_game" in _errors(orphan)
    assert "set_type" in _errors(untyped)


@pytest.mark.django_db
def test_a_subsets_parent_must_be_a_core_game(core, bonus):
    nested = Game(
        title="Nested",
        console=core.console,
        parent_game=bonus,
        set_type=SET_TYPE_CHALLENGE,
        set_title="Nested",
    )

    assert "parent_game" in _errors(nested)


@pytest.mark.django_db
def test_a_subset_is_on_its_parents_console(core):
    saturn = Console.objects.create(ra_id=SATURN_RA_ID, name="Saturn", short_name="SAT")
    elsewhere = Game(
        title=BONUS_TITLE,
        console=saturn,
        parent_game=core,
        set_type=SET_TYPE_BONUS,
        set_title="Bonus",
    )

    assert "console" in _errors(elsewhere)


@pytest.mark.django_db
def test_a_game_with_subsets_cannot_become_a_subset(console, core, bonus):
    other_core = Game.objects.create(title="Crash 2", console=console)
    core.parent_game = other_core
    core.set_type = SET_TYPE_BONUS
    core.set_title = "Bonus"

    assert "set_type" in _errors(core)


@pytest.mark.django_db
@pytest.mark.parametrize("set_type", [SET_TYPE_BONUS, SET_TYPE_CHALLENGE])
def test_a_game_with_hashes_cannot_become_a_bonus_or_challenge_subset(console, core, set_type):
    hashed = Game.objects.create(title="Crash Prototype", console=console)
    GameHash.objects.create(game=hashed, md5=MD5, label="Disc")
    hashed.parent_game = core
    hashed.set_type = set_type
    hashed.set_title = "Bonus"

    assert "set_type" in _errors(hashed)


@pytest.mark.django_db
def test_a_game_with_hashes_can_become_a_specialty_subset(console, core):
    hashed = Game.objects.create(title="Crash Japan", console=console)
    GameHash.objects.create(game=hashed, md5=MD5, label="Disc")
    hashed.parent_game = core
    hashed.set_type = SET_TYPE_SPECIALTY
    hashed.set_title = "Japanese"

    hashed.full_clean()


@pytest.mark.django_db
def test_a_core_games_subsets_follow_it_to_another_console(core, bonus):
    saturn = Console.objects.create(ra_id=SATURN_RA_ID, name="Saturn", short_name="SAT")

    core.console = saturn
    core.save()

    bonus.refresh_from_db()
    assert bonus.console == saturn
    bonus.full_clean()


@pytest.mark.django_db
def test_a_subset_needs_a_set_title(core):
    untitled = Game(
        title=BONUS_TITLE, console=core.console, parent_game=core, set_type=SET_TYPE_BONUS
    )

    assert "set_title" in _errors(untitled)


@pytest.mark.django_db
@pytest.mark.parametrize("set_type", [SET_TYPE_BONUS, SET_TYPE_CHALLENGE])
def test_a_bonus_or_challenge_subset_takes_no_hash(core, set_type):
    subset = _subset(core, set_type=set_type)

    with pytest.raises(ValidationError):
        GameHash(game=subset, md5=MD5, label="Disc").full_clean()


@pytest.mark.django_db
@pytest.mark.parametrize("set_type", [SET_TYPE_SPECIALTY, SET_TYPE_EXCLUSIVE])
def test_a_specialty_or_exclusive_subset_takes_a_hash(core, set_type):
    subset = _subset(core, set_type=set_type)

    GameHash(game=subset, md5=MD5, label="Disc").full_clean()


@pytest.mark.django_db
def test_a_code_note_belongs_to_the_core_game(core, bonus, player):
    CodeNote(game=core, author=player, address="0x10", note="Lives").full_clean()
    with pytest.raises(ValidationError):
        CodeNote(game=bonus, author=player, address="0x10", note="Lives").full_clean()


# --- Preferences ---


@pytest.mark.django_db
def test_a_preference_is_unique_per_player_and_subset(player, bonus):
    UserSetPreference.objects.create(user=player, subset_game=bonus, opted_in=True)
    with pytest.raises(IntegrityError), transaction.atomic():
        UserSetPreference.objects.create(user=player, subset_game=bonus, opted_in=False)


@pytest.mark.django_db
def test_a_preference_is_for_a_bonus_or_challenge_subset(player, core):
    challenge = _subset(core, set_type=SET_TYPE_CHALLENGE, title="Deathless", set_title="Dl")
    specialty = _subset(core, set_type=SET_TYPE_SPECIALTY, title="Japan", set_title="Japan")

    UserSetPreference(user=player, subset_game=challenge, opted_in=True).full_clean()
    for game in (core, specialty):
        with pytest.raises(ValidationError):
            UserSetPreference(user=player, subset_game=game, opted_in=True).full_clean()


# --- Admin ---


def _management(prefix, total, initial=0):
    return {f"{prefix}-TOTAL_FORMS": str(total), f"{prefix}-INITIAL_FORMS": str(initial)}


@pytest.mark.django_db
def test_admin_adds_a_game_with_a_subset_on_its_console(client, admin_user, console):
    client.force_login(admin_user)

    response = client.post(
        "/admin/games/game/add/",
        {
            "title": CORE_TITLE,
            "console": console.pk,
            **_management("hashes", 0),
            **_management("subsets", 1),
            "subsets-0-set_type": SET_TYPE_BONUS,
            "subsets-0-set_title": "Bonus",
            "subsets-0-title": BONUS_TITLE,
        },
    )

    assert response.status_code == HTTPStatus.FOUND
    core = Game.objects.get(title=CORE_TITLE)
    subset = Game.objects.get(title=BONUS_TITLE)
    assert (subset.parent_game, subset.console, subset.set_type) == (core, console, "bonus")


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("fields", "missing"),
    [
        ({"subsets-0-set_title": "Bonus"}, "set_type"),
        ({"subsets-0-set_type": "bonus"}, "set_title"),
    ],
)
def test_admin_inline_subset_needs_a_type_and_a_title(client, admin_user, core, fields, missing):
    client.force_login(admin_user)

    response = client.post(
        f"/admin/games/game/{core.pk}/change/",
        {
            "title": CORE_TITLE,
            "console": core.console.pk,
            **_management("hashes", 0),
            **_management("subsets", 1),
            "subsets-0-title": BONUS_TITLE,
            **fields,
        },
    )

    assert response.status_code == HTTPStatus.OK
    assert missing in response.context["inline_admin_formsets"][1].formset.errors[0]
    assert not core.subsets.exists()


@pytest.mark.django_db
def test_admin_refuses_a_hash_on_a_bonus_subset(client, admin_user, bonus):
    client.force_login(admin_user)

    response = client.post(
        f"/admin/games/game/{bonus.pk}/change/",
        {
            "title": BONUS_TITLE,
            "console": bonus.console.pk,
            "parent_game": bonus.parent_game.pk,
            "set_type": SET_TYPE_BONUS,
            "set_title": "Bonus",
            **_management("hashes", 1),
            "hashes-0-md5": MD5,
            "hashes-0-label": "Disc",
        },
    )

    assert response.status_code == HTTPStatus.OK
    assert not GameHash.objects.exists()


@pytest.mark.django_db
def test_admin_moving_a_core_game_moves_its_subsets(client, admin_user, core, bonus):
    saturn = Console.objects.create(ra_id=SATURN_RA_ID, name="Saturn", short_name="SAT")
    client.force_login(admin_user)

    response = client.post(
        f"/admin/games/game/{core.pk}/change/",
        {
            "title": CORE_TITLE,
            "console": saturn.pk,
            **_management("hashes", 0),
            **_management("subsets", 1, initial=1),
            "subsets-0-id": bonus.pk,
            "subsets-0-parent_game": core.pk,
            "subsets-0-set_type": SET_TYPE_BONUS,
            "subsets-0-set_title": "Bonus",
            "subsets-0-title": BONUS_TITLE,
        },
    )

    assert response.status_code == HTTPStatus.FOUND
    bonus.refresh_from_db()
    assert bonus.console == saturn


@pytest.mark.django_db
def test_admin_shows_subsets_inline_on_core_games_only(client, admin_user, core, bonus):
    client.force_login(admin_user)

    core_page = client.get(f"/admin/games/game/{core.pk}/change/")
    subset_page = client.get(f"/admin/games/game/{bonus.pk}/change/")

    assert BONUS_TITLE in core_page.content.decode()
    assert len(core_page.context["inline_admin_formsets"]) == 2
    assert len(subset_page.context["inline_admin_formsets"]) == 1


@pytest.mark.django_db
def test_admin_lists_the_preferences(client, admin_user, player, bonus):
    UserSetPreference.objects.create(user=player, subset_game=bonus, opted_in=True)
    client.force_login(admin_user)

    response = client.get("/admin/games/usersetpreference/")

    assert response.status_code == HTTPStatus.OK
    assert BONUS_TITLE in response.content.decode()


# --- Listings hold core games only ---


@pytest.fixture
def played(player, core, bonus):
    """The player played both sets and unlocked the official achievement of each in hardcore."""
    sets = (core, bonus)
    for game in sets:
        PlayerGame.objects.create(user=player, game=game)
        achievement = _official(game, player)
        for hardcore in (False, True):
            UserUnlock.objects.create(
                user=player, achievement=achievement, hardcore=hardcore, unlocked_at=timezone.now()
            )
    player.softcore_points = player.hardcore_points = len(sets) * POINTS
    player.save(update_fields=["softcore_points", "hardcore_points"])
    return player


@pytest.mark.django_db
def test_the_games_list_and_home_leave_subsets_out(client, core, bonus, played):
    games_list = client.get(reverse("games_list"))
    home = client.get(reverse("home"))

    assert [card["game"] for card in games_list.context["cards"]] == [core]
    assert [item["game"] for item in home.context["sets"]] == [core]
    assert BONUS_TITLE not in games_list.content.decode()
    # The site's totals still count the subset's achievement and unlocks.
    assert home.context["numbers"]["achievements"] == len((core, bonus))


@pytest.mark.django_db
def test_games_played_count_core_games_only(client, core, played):
    assert stats.games_played_count(played) == 1
    assert [progress.played.game for progress in stats.played_games_progress(played)] == [core]
    summary = client.get(reverse("api-user", args=[played.username])).json()
    assert summary["GamesPlayed"] == 1
    profile = client.get(reverse("user_detail", args=[played.username]))
    assert profile.context["games_played"] == 1


@pytest.mark.django_db
def test_games_played_count_an_exclusive_disc_as_its_core_game(core, player):
    exclusive = _subset(core, SET_TYPE_EXCLUSIVE, set_title="Prototype")
    PlayerGame.objects.create(user=player, game=exclusive)

    assert stats.games_played_count(player) == 1


@pytest.mark.django_db
def test_ranking_counts_subset_unlocks_but_platinums_of_core_games_only(core, bonus, played):
    tally = stats.ranking_tallies([played.pk], hardcore=True)[played.pk]

    assert tally == stats.RankingTally(unlocked=len((core, bonus)), platinums=1)

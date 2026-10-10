"""Subsets over the rcheevos protocol: which sets a disc hash serves (RAWeb's
`ResolveAchievementSetsAction`), the session a hash is recorded on, unlocks and completion per set,
and the code notes a subset shares with its parent game."""

from http import HTTPStatus

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone

from apps.achievements.models import Achievement, CodeNote, UserUnlock
from apps.anticheat.detection import award_validation_hash
from apps.api.handlers import API_TOKEN_LIFETIME
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
from apps.images.catalog import versioned_game_icon_path
from apps.leaderboards.models import Leaderboard

User = get_user_model()

PLAYER = "player"
PLAYER_TOKEN = "player-token"
OTHER = "other"
OTHER_TOKEN = "other-token"
PLAYSTATION_RA_ID = 12
CORE_MD5 = "c" * MD5_HEX_DIGITS
SPECIALTY_MD5 = "5" * MD5_HEX_DIGITS
EXCLUSIVE_MD5 = "e" * MD5_HEX_DIGITS
BONUS_MD5 = "b" * MD5_HEX_DIGITS
UNKNOWN_MD5 = "0" * MD5_HEX_DIGITS
CORE_RICH_PRESENCE = "Display:\nCore"
SPECIALTY_RICH_PRESENCE = "Display:\nSpecialty"
EXCLUSIVE_RICH_PRESENCE = "Display:\nExclusive"
POINTS = 10
UNKNOWN_GAME_ID = 999_999
LIVES_ADDRESS = 0x1234
HEALTH_ADDRESS = 0x1235
# One unlocker among the subset's two players.
HALF_THE_PLAYERS = 50.0


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


def _user(username, token):
    user = User.objects.create_user(username=username, password="pw")
    user.api_token = token
    user.api_token_expires_at = timezone.now() + API_TOKEN_LIFETIME
    user.save(update_fields=["api_token", "api_token_expires_at"])
    return user


@pytest.fixture
def player(db):
    return _user(PLAYER, PLAYER_TOKEN)


@pytest.fixture
def other(db):
    return _user(OTHER, OTHER_TOKEN)


def _official(game, author, title):
    return Achievement.objects.create(
        game=game,
        author=author,
        title=title,
        description=title,
        points=POINTS,
        mem_addr="0xH0001=1",
        status=Achievement.STATUS_OFFICIAL,
    )


class Sets:
    """Crash with a core hash, a bonus, a challenge, a specialty and an exclusive subset."""

    def __init__(self, author):
        self.console = Console.objects.create(
            ra_id=PLAYSTATION_RA_ID, name="PlayStation", short_name="PS1"
        )
        self.core = Game.objects.create(
            title="Crash Bandicoot", console=self.console, rich_presence_patch=CORE_RICH_PRESENCE
        )
        GameHash.objects.create(game=self.core, md5=CORE_MD5, label="NTSC-U")
        self.bonus = self._subset(SET_TYPE_BONUS, "Bonus")
        self.challenge = self._subset(SET_TYPE_CHALLENGE, "Deathless")
        self.specialty = self._subset(
            SET_TYPE_SPECIALTY, "Japanese", rich_presence_patch=SPECIALTY_RICH_PRESENCE
        )
        GameHash.objects.create(game=self.specialty, md5=SPECIALTY_MD5, label="NTSC-J")
        self.exclusive = self._subset(SET_TYPE_EXCLUSIVE, "Prototype")
        GameHash.objects.create(game=self.exclusive, md5=EXCLUSIVE_MD5, label="Prototype")
        self.achievements = {
            game.pk: _official(game, author, f"{game.title} one")
            for game in (self.core, self.bonus, self.challenge, self.specialty, self.exclusive)
        }
        self.leaderboard = Leaderboard.objects.create(
            game=self.core,
            title="Stage time",
            description="d",
            mem_addr="STA:0xH0001=1::CAN:0xH0002=1::SUB:0xH0003=1::VAL:0xH0004",
            format="FRAMES",
        )

    def _subset(self, set_type, set_title, **fields):
        return Game.objects.create(
            title=f"Crash Bandicoot [Subset - {set_title}]",
            console=self.console,
            parent_game=self.core,
            set_type=set_type,
            set_title=set_title,
            **fields,
        )


@pytest.fixture
def sets(player):
    return Sets(author=player)


def _opt(user, subset, opted_in=True):
    UserSetPreference.objects.create(user=user, subset_game=subset, opted_in=opted_in)


def _post(client, **params):
    return client.post("/dorequest.php", params).json()


def _achievementsets(client, **params):
    return _post(client, r="achievementsets", u=PLAYER, t=PLAYER_TOKEN, **params)


def _set_ids(data):
    return [served["AchievementSetId"] for served in data["Sets"]]


# --- achievementsets ---


@pytest.mark.django_db
def test_core_hash_without_preferences_serves_the_core_set_alone(client, sets):
    data = _achievementsets(client, m=CORE_MD5)

    assert data["Success"] is True
    assert data["GameId"] == sets.core.pk
    assert data["Title"] == sets.core.title
    assert data["ConsoleId"] == PLAYSTATION_RA_ID
    assert data["RichPresenceGameId"] == sets.core.pk
    assert data["RichPresencePatch"] == CORE_RICH_PRESENCE
    assert data["Sets"] == [
        {
            "AchievementSetId": sets.core.pk,
            "GameId": sets.core.pk,
            "Title": None,
            "Type": "core",
            "ImageIconUrl": f"http://testserver{versioned_game_icon_path(sets.core)}",
            "Achievements": data["Sets"][0]["Achievements"],
            "Leaderboards": data["Sets"][0]["Leaderboards"],
        }
    ]
    assert [a["ID"] for a in data["Sets"][0]["Achievements"]] == [
        sets.achievements[sets.core.pk].pk
    ]
    assert [lb["ID"] for lb in data["Sets"][0]["Leaderboards"]] == [sets.leaderboard.pk]


@pytest.mark.django_db
def test_core_hash_serves_the_opted_in_subsets_core_first_then_challenge_then_bonus(
    client, player, sets
):
    _opt(player, sets.bonus)
    _opt(player, sets.challenge)

    data = _achievementsets(client, m=CORE_MD5)

    assert data["GameId"] == sets.core.pk
    assert _set_ids(data) == [sets.core.pk, sets.challenge.pk, sets.bonus.pk]
    core, challenge, bonus = data["Sets"]
    assert (core["Type"], core["Title"]) == ("core", None)
    assert (challenge["Type"], challenge["Title"]) == ("challenge", "Deathless")
    assert (bonus["Type"], bonus["Title"]) == ("bonus", "Bonus")
    assert bonus["GameId"] == sets.bonus.pk
    assert bonus["ImageIconUrl"] == f"http://testserver{versioned_game_icon_path(sets.bonus)}"
    assert [a["ID"] for a in bonus["Achievements"]] == [sets.achievements[sets.bonus.pk].pk]
    assert bonus["Leaderboards"] == []


@pytest.mark.django_db
def test_an_opted_out_subset_is_not_served(client, player, sets):
    _opt(player, sets.bonus, opted_in=False)
    _opt(player, sets.challenge)

    data = _achievementsets(client, m=CORE_MD5)

    assert _set_ids(data) == [sets.core.pk, sets.challenge.pk]


@pytest.mark.django_db
def test_another_players_opt_in_does_not_apply(client, other, sets):
    _opt(other, sets.bonus)

    data = _achievementsets(client, m=CORE_MD5)

    assert _set_ids(data) == [sets.core.pk]


@pytest.mark.django_db
def test_specialty_hash_serves_the_core_the_specialty_and_the_opted_in_subsets(
    client, player, sets
):
    _opt(player, sets.bonus)

    data = _achievementsets(client, m=SPECIALTY_MD5)

    assert data["GameId"] == sets.core.pk
    assert data["Title"] == sets.core.title
    assert _set_ids(data) == [sets.core.pk, sets.specialty.pk, sets.bonus.pk]
    assert [served["Type"] for served in data["Sets"]] == ["core", "specialty", "bonus"]
    assert data["Sets"][1]["Title"] == "Japanese"
    assert data["RichPresenceGameId"] == sets.specialty.pk
    assert data["RichPresencePatch"] == SPECIALTY_RICH_PRESENCE


@pytest.mark.django_db
def test_specialty_without_rich_presence_serves_the_parents(client, sets):
    Game.objects.filter(pk=sets.specialty.pk).update(rich_presence_patch="")

    data = _achievementsets(client, m=SPECIALTY_MD5)

    assert data["RichPresenceGameId"] == sets.core.pk
    assert data["RichPresencePatch"] == CORE_RICH_PRESENCE


@pytest.mark.django_db
def test_exclusive_hash_serves_only_its_set_under_the_core_game(client, player, sets):
    _opt(player, sets.bonus)

    data = _achievementsets(client, m=EXCLUSIVE_MD5)

    assert data["GameId"] == sets.core.pk
    assert data["Title"] == sets.core.title
    assert _set_ids(data) == [sets.exclusive.pk]
    exclusive = data["Sets"][0]
    assert (exclusive["Type"], exclusive["Title"]) == ("exclusive", "Prototype")
    assert exclusive["GameId"] == sets.exclusive.pk
    assert [a["ID"] for a in exclusive["Achievements"]] == [sets.achievements[sets.exclusive.pk].pk]
    assert data["RichPresenceGameId"] == sets.core.pk
    assert data["RichPresencePatch"] == CORE_RICH_PRESENCE


@pytest.mark.django_db
def test_exclusive_with_rich_presence_serves_its_own(client, sets):
    Game.objects.filter(pk=sets.exclusive.pk).update(rich_presence_patch=EXCLUSIVE_RICH_PRESENCE)

    data = _achievementsets(client, m=EXCLUSIVE_MD5)

    assert data["RichPresenceGameId"] == sets.exclusive.pk
    assert data["RichPresencePatch"] == EXCLUSIVE_RICH_PRESENCE


@pytest.mark.django_db
def test_a_hash_linked_to_a_bonus_subset_loads_its_parent(client, player, sets):
    # Validation keeps hashes off bonus subsets; a row written around it still loads sensibly.
    GameHash.objects.create(game=sets.bonus, md5=BONUS_MD5, label="Legacy")
    _opt(player, sets.bonus)

    data = _achievementsets(client, m=BONUS_MD5)

    assert data["GameId"] == sets.core.pk
    assert _set_ids(data) == [sets.core.pk, sets.bonus.pk]
    assert data["RichPresenceGameId"] == sets.core.pk


@pytest.mark.django_db
def test_game_id_alone_serves_that_game_as_its_own_core_set(client, player, sets):
    _opt(player, sets.challenge)

    data = _achievementsets(client, g=sets.bonus.pk)

    assert data["GameId"] == sets.bonus.pk
    assert data["Title"] == sets.bonus.title
    assert data["RichPresenceGameId"] == sets.bonus.pk
    assert _set_ids(data) == [sets.bonus.pk]
    assert (data["Sets"][0]["Type"], data["Sets"][0]["Title"]) == ("core", None)


@pytest.mark.django_db
def test_game_id_alone_of_a_core_game_serves_no_subsets(client, player, sets):
    _opt(player, sets.bonus)

    data = _achievementsets(client, g=sets.core.pk)

    assert _set_ids(data) == [sets.core.pk]


@pytest.mark.django_db
def test_unknown_hash_or_game_is_not_found(client, sets):
    for params in ({"m": UNKNOWN_MD5}, {"g": UNKNOWN_GAME_ID}):
        data = _achievementsets(client, **params)
        assert data["Success"] is False
        assert data["Code"] == "not_found"


@pytest.mark.django_db
def test_rarity_is_over_the_players_of_each_sets_own_game(client, player, other, sets):
    _opt(player, sets.bonus)
    bonus_achievement = sets.achievements[sets.bonus.pk]
    # Four core players, two of them bonus players; one unlocked the bonus achievement.
    for username in ("p1", "p2", "p3", "p4"):
        PlayerGame.objects.create(user=_user(username, f"{username}-token"), game=sets.core)
    for user in (player, other):
        PlayerGame.objects.create(user=user, game=sets.bonus)
    UserUnlock.objects.create(
        user=other, achievement=bonus_achievement, hardcore=False, unlocked_at=timezone.now()
    )

    data = _achievementsets(client, m=CORE_MD5)

    bonus = data["Sets"][1]["Achievements"][0]
    assert bonus["ID"] == bonus_achievement.pk
    assert bonus["Rarity"] == HALF_THE_PLAYERS
    assert bonus["RarityHardcore"] == 0.0


# --- startsession ---


def _startsession(client, **params):
    return _post(client, r="startsession", u=PLAYER, t=PLAYER_TOKEN, **params)


def _unlock(user, achievement, hardcore=False):
    return UserUnlock.objects.create(
        user=user, achievement=achievement, hardcore=hardcore, unlocked_at=timezone.now()
    )


@pytest.mark.django_db
def test_startsession_by_hash_returns_the_unlocks_of_every_served_set(client, player, sets):
    _opt(player, sets.bonus)
    served = [sets.core, sets.specialty, sets.bonus]
    for game in (*served, sets.challenge, sets.exclusive):
        _unlock(player, sets.achievements[game.pk])

    data = _startsession(client, g=sets.core.pk, h=0, m=SPECIALTY_MD5)

    assert data["Success"] is True
    assert sorted(unlock["ID"] for unlock in data["Unlocks"]) == sorted(
        sets.achievements[game.pk].pk for game in served
    )
    assert data["HardcoreUnlocks"] == []


@pytest.mark.django_db
def test_startsession_records_a_specialty_session_on_the_specialty_game(client, player, sets):
    _startsession(client, g=sets.core.pk, h=1, m=SPECIALTY_MD5)

    session = PlayerGame.objects.get(user=player)
    assert session.game == sets.specialty
    assert session.hardcore is True


@pytest.mark.django_db
def test_startsession_records_a_core_session_on_the_core_game(client, player, sets):
    _opt(player, sets.bonus)

    _startsession(client, g=sets.core.pk, h=0, m=CORE_MD5)

    assert PlayerGame.objects.get(user=player).game == sets.core


@pytest.mark.django_db
def test_startsession_on_a_bonus_hash_records_the_parents_session(client, player, sets):
    GameHash.objects.create(game=sets.bonus, md5=BONUS_MD5, label="Legacy")

    _startsession(client, g=sets.core.pk, h=0, m=BONUS_MD5)

    assert PlayerGame.objects.get(user=player).game == sets.core


@pytest.mark.django_db
def test_startsession_with_an_unknown_hash_falls_back_to_the_game_id(client, player, sets):
    _opt(player, sets.bonus)
    _unlock(player, sets.achievements[sets.core.pk])
    _unlock(player, sets.achievements[sets.bonus.pk])

    data = _startsession(client, g=sets.core.pk, h=0, m=UNKNOWN_MD5)

    assert data["Success"] is True
    assert PlayerGame.objects.get(user=player).game == sets.core
    assert [unlock["ID"] for unlock in data["Unlocks"]] == [sets.achievements[sets.core.pk].pk]


@pytest.mark.django_db
def test_startsession_with_an_unknown_game_is_not_found_whatever_the_hash(client, player, sets):
    data = _startsession(client, g=UNKNOWN_GAME_ID, h=0, m=CORE_MD5)

    assert data["Code"] == "not_found"
    assert not PlayerGame.objects.exists()


# --- ping ---


def _ping(client, **params):
    return _post(client, r="ping", u=PLAYER, t=PLAYER_TOKEN, **params)


@pytest.mark.django_db
def test_ping_by_hash_records_the_presence_on_the_hashs_session_game(client, player, sets):
    _startsession(client, g=sets.core.pk, h=0, m=SPECIALTY_MD5)

    data = _ping(client, g=sets.core.pk, m="In Japan", h=0, x=SPECIALTY_MD5)

    assert data == {"Success": True}
    session = PlayerGame.objects.get(user=player)
    assert session.game == sets.specialty
    assert session.last_rich_presence == "In Japan"


@pytest.mark.django_db
def test_ping_on_an_exclusive_hash_records_the_exclusive_session(client, player, sets):
    _ping(client, g=sets.core.pk, m="Prototype", h=0, x=EXCLUSIVE_MD5)

    assert PlayerGame.objects.get(user=player).game == sets.exclusive


@pytest.mark.django_db
@pytest.mark.parametrize("hash_params", [{}, {"h": 0, "x": UNKNOWN_MD5}])
def test_ping_without_a_known_hash_records_the_game_id(client, player, sets, hash_params):
    _ping(client, g=sets.core.pk, m="Playing", **hash_params)

    assert PlayerGame.objects.get(user=player).game == sets.core


@pytest.mark.django_db
def test_ping_with_an_unknown_game_is_not_found_whatever_the_hash(client, player, sets):
    data = _ping(client, g=UNKNOWN_GAME_ID, m="Playing", h=0, x=CORE_MD5)

    assert data["Code"] == "not_found"
    assert not PlayerGame.objects.exists()


# --- awardachievement ---


def _award(client, achievement):
    return _post(
        client,
        r="awardachievement",
        u=PLAYER,
        t=PLAYER_TOKEN,
        a=achievement.pk,
        h=1,
        v=award_validation_hash(achievement.pk, PLAYER, True, 0),
    )


@pytest.mark.django_db
def test_award_counts_the_remaining_achievements_of_the_achievements_own_set(client, player, sets):
    _official(sets.bonus, player, "Bonus two")

    first = _award(client, sets.achievements[sets.bonus.pk])

    assert first["Success"] is True
    # Only the bonus set counts: the locked core achievement is not remaining here.
    assert first["AchievementsRemaining"] == 1
    last = _award(client, Achievement.objects.get(title="Bonus two"))
    assert last["AchievementsRemaining"] == 0
    core = _award(client, sets.achievements[sets.core.pk])
    assert core["AchievementsRemaining"] == 0


# --- code notes ---


@pytest.fixture
def lives(sets, player):
    return CodeNote.objects.create(
        game=sets.core, author=player, address=f"0x{LIVES_ADDRESS:x}", note="Lives"
    )


@pytest.mark.django_db
def test_codenotes2_of_a_subset_serves_the_parents_notes(client, lives, sets):
    for game in (sets.core, sets.bonus, sets.specialty):
        data = _post(client, r="codenotes2", g=game.pk)
        assert data["CodeNotes"] == [{"User": PLAYER, "Address": "0x001234", "Note": "Lives"}]


@pytest.mark.django_db
def test_submitcodenote_on_a_subset_writes_the_parents_note(client, lives, sets):
    data = _post(
        client,
        r="submitcodenote",
        u=PLAYER,
        t=PLAYER_TOKEN,
        g=sets.bonus.pk,
        m=LIVES_ADDRESS,
        n="Lives (1 byte)",
    )

    assert data == {"Success": True}
    lives.refresh_from_db()
    assert lives.note == "Lives (1 byte)"
    assert not CodeNote.objects.filter(game=sets.bonus).exists()


@pytest.mark.django_db
def test_submitcodenotes_on_a_subset_writes_the_parents_notes(client, sets, player):
    data = _post(
        client,
        r="submitcodenotes",
        u=PLAYER,
        t=PLAYER_TOKEN,
        g=sets.specialty.pk,
        n=f"{LIVES_ADDRESS}:Lives\n{HEALTH_ADDRESS}:Health",
    )

    assert data == {"Success": True, "SuccessfulAddresses": [LIVES_ADDRESS, HEALTH_ADDRESS]}
    assert sorted(CodeNote.objects.filter(game=sets.core).values_list("note", flat=True)) == [
        "Health",
        "Lives",
    ]
    assert not CodeNote.objects.exclude(game=sets.core).exists()


# --- submitgametitle ---


def _submitgametitle(client, staff, game):
    return _post(
        client,
        r="submitgametitle",
        u=staff.username,
        t="staff-token",
        c=PLAYSTATION_RA_ID,
        m=BONUS_MD5,
        g=game.pk,
        d="Disc",
    )


@pytest.fixture
def staff(db):
    user = _user("staff", "staff-token")
    user.is_staff = True
    user.save(update_fields=["is_staff"])
    return user


@pytest.mark.django_db
def test_submitgametitle_refuses_a_hash_for_a_bonus_subset(client, staff, sets):
    data = _submitgametitle(client, staff, sets.bonus)

    assert data["Code"] == "invalid_parameter"
    assert data["Status"] == HTTPStatus.UNPROCESSABLE_ENTITY
    assert not GameHash.objects.filter(md5=BONUS_MD5).exists()


@pytest.mark.django_db
def test_submitgametitle_links_a_hash_to_a_specialty_subset(client, staff, sets):
    data = _submitgametitle(client, staff, sets.specialty)

    assert data["Success"] is True
    assert GameHash.objects.get(md5=BONUS_MD5).game == sets.specialty

from datetime import timedelta
from http import HTTPStatus

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.utils import timezone

from apps.accounts.models import API_TOKEN_HEX_LENGTH
from apps.achievements.models import Achievement, UserUnlock
from apps.anticheat.detection import (
    AWARD_RATE_KEY,
    AWARD_RATE_LIMIT,
    AWARD_RATE_WINDOW,
    EARLY_UNLOCK_WINDOW,
    UNLOCK_BURST_THRESHOLD,
    UNLOCK_BURST_WINDOW,
    award_rate_exceeded,
    award_validation_hash,
    leaderboard_validation_hash,
)
from apps.anticheat.models import SuspiciousActivity
from apps.api.handlers import API_TOKEN_LIFETIME, MAX_UINT32, UNLOCK_MAX_AGE
from apps.games.models import Console, Game, PlayerGame
from apps.leaderboards.models import Leaderboard, LeaderboardEntry

User = get_user_model()

SUSPICIOUS_CHANGELIST_URL = "/admin/anticheat/suspiciousactivity/"

PLAYER = "player"
TOKEN = "t" * API_TOKEN_HEX_LENGTH
# Signatures computed by rcheevos v12.4.0 itself (`rc_api_init_award_achievement_request` and
# `rc_api_init_submit_lboard_entry_request`) for user "player".
ACHIEVEMENT_ID = 12345
SECONDS_SINCE_UNLOCK = 37
V_AWARD_HARDCORE = "27bc2a1013b15b04be91fcdea74a2cb6"
V_AWARD_SOFTCORE = "d9b7a8bad1379821e952ad181bd5a5bd"
V_AWARD_HARDCORE_RETRY = "5482227bad805503fe60bb0d1882c073"
LEADERBOARD_ID = 678
SCORE = -1500
SECONDS_SINCE_COMPLETION = 5
V_LBENTRY = "298fe5dce471b4a628690193b3a9e475"
V_LBENTRY_RETRY = "316b18f520ab0229d8b43d26d6a36f05"

MISSING_PARAMETER = {
    "Success": False,
    "Error": "One or more required parameters is missing.",
    "Status": HTTPStatus.UNPROCESSABLE_ENTITY,
    "Code": "missing_parameter",
}
INVALID_V = {
    "Success": False,
    "Error": "Invalid v: the validation hash does not match.",
    "Status": HTTPStatus.UNPROCESSABLE_ENTITY,
    "Code": "invalid_parameter",
}


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def suspect(db):
    return User.objects.create_user(username="suspect", password="pw")


@pytest.fixture
def player(db):
    user = User.objects.create_user(username=PLAYER, password="pw")
    user.api_token = TOKEN
    user.api_token_expires_at = timezone.now() + API_TOKEN_LIFETIME
    user.save(update_fields=["api_token", "api_token_expires_at"])
    return user


@pytest.fixture
def game(db):
    console = Console.objects.create(ra_id=12, name="PlayStation", short_name="PS1")
    return Game.objects.create(title="Crash Bandicoot", console=console)


@pytest.fixture
def achievement(game, player):
    return Achievement.objects.create(
        pk=ACHIEVEMENT_ID,
        game=game,
        author=player,
        title="Signed",
        description="d",
        points=10,
        mem_addr="0xH0001=1",
        status=Achievement.STATUS_OFFICIAL,
    )


@pytest.fixture
def leaderboard(game):
    return Leaderboard.objects.create(
        pk=LEADERBOARD_ID, game=game, title="Fastest", mem_addr="STA:0=1::CAN:0=1::SUB:0=1::VAL:0"
    )


def _award(client, **params):
    return client.post(
        "/dorequest.php", {"r": "awardachievement", "u": PLAYER, "t": TOKEN, **params}
    )


def _submit(client, **params):
    return client.post("/dorequest.php", {"r": "submitlbentry", "u": PLAYER, "t": TOKEN, **params})


def _flag(user, kind=SuspiciousActivity.Kind.UNLOCK_BURST, **detail):
    return SuspiciousActivity.objects.create(user=user, kind=kind, detail=detail)


def _run_review_action(admin_client, action, activities):
    return admin_client.post(
        SUSPICIOUS_CHANGELIST_URL,
        {"action": action, "_selected_action": [activity.pk for activity in activities]},
    )


# --- validation hashes ---


@pytest.mark.parametrize(
    ("hardcore", "seconds_since_unlock", "expected"),
    [
        (True, 0, V_AWARD_HARDCORE),
        (False, 0, V_AWARD_SOFTCORE),
        (True, SECONDS_SINCE_UNLOCK, V_AWARD_HARDCORE_RETRY),
    ],
)
def test_award_validation_hash_matches_rcheevos(hardcore, seconds_since_unlock, expected):
    assert award_validation_hash(ACHIEVEMENT_ID, PLAYER, hardcore, seconds_since_unlock) == (
        expected
    )


@pytest.mark.parametrize(
    ("seconds_since_completion", "expected"),
    [(0, V_LBENTRY), (SECONDS_SINCE_COMPLETION, V_LBENTRY_RETRY)],
)
def test_leaderboard_validation_hash_matches_rcheevos(seconds_since_completion, expected):
    assert (
        leaderboard_validation_hash(LEADERBOARD_ID, PLAYER, SCORE, seconds_since_completion)
        == expected
    )


# --- awardachievement signature ---


def _assert_flagged_signature(user, reason, **detail):
    activity = SuspiciousActivity.objects.get(user=user)
    assert activity.kind == SuspiciousActivity.Kind.INVALID_SIGNATURE
    assert activity.review_status == SuspiciousActivity.ReviewStatus.PENDING
    assert activity.detail == {"reason": reason, **detail}


@pytest.mark.django_db
@pytest.mark.parametrize(("hardcore", "v"), [("1", V_AWARD_HARDCORE), ("0", V_AWARD_SOFTCORE)])
def test_award_with_rcheevos_signature_unlocks(client, player, achievement, hardcore, v):
    response = _award(client, a=ACHIEVEMENT_ID, h=hardcore, v=v)

    assert response.status_code == HTTPStatus.OK
    assert response.json()["Success"] is True
    assert UserUnlock.objects.filter(user=player, achievement=achievement).exists()
    assert not SuspiciousActivity.objects.exists()


@pytest.mark.django_db
def test_award_retry_is_dated_back_by_its_seconds_since_unlock(client, player, achievement):
    before = timezone.now()

    response = _award(
        client, a=ACHIEVEMENT_ID, h="1", o=SECONDS_SINCE_UNLOCK, v=V_AWARD_HARDCORE_RETRY
    )

    assert response.json()["Success"] is True
    delay = timedelta(seconds=SECONDS_SINCE_UNLOCK)
    unlocks = UserUnlock.objects.filter(user=player)
    assert {unlock.hardcore for unlock in unlocks} == {False, True}
    for unlock in unlocks:
        assert before - delay <= unlock.unlocked_at <= timezone.now() - delay


@pytest.mark.django_db
def test_backdated_award_dates_the_first_play_it_creates_no_later_than_the_unlock(
    client, player, achievement
):
    _award(client, a=ACHIEVEMENT_ID, h="1", o=SECONDS_SINCE_UNLOCK, v=V_AWARD_HARDCORE_RETRY)

    player_game = PlayerGame.objects.get(user=player, game=achievement.game)
    first_unlock = UserUnlock.objects.filter(user=player).earliest("unlocked_at")
    assert player_game.first_played_at == first_unlock.unlocked_at


@pytest.mark.django_db
def test_award_takes_a_zero_seconds_since_unlock_as_unsent(client, player, achievement):
    response = _award(client, a=ACHIEVEMENT_ID, h="1", o="0", v=V_AWARD_HARDCORE)

    assert response.json()["Success"] is True


@pytest.mark.django_db
def test_award_bounds_how_far_back_an_unlock_is_dated(client, player, achievement):
    before = timezone.now()
    v = award_validation_hash(ACHIEVEMENT_ID, PLAYER, False, MAX_UINT32)

    response = _award(client, a=ACHIEVEMENT_ID, h="0", o=MAX_UINT32, v=v)

    assert response.json()["Success"] is True
    unlock = UserUnlock.objects.get(user=player)
    assert before - UNLOCK_MAX_AGE <= unlock.unlocked_at <= timezone.now() - UNLOCK_MAX_AGE


@pytest.mark.django_db
def test_award_without_v_is_rejected_and_flagged(client, player, achievement):
    response = _award(client, a=ACHIEVEMENT_ID, h="1")

    assert response.status_code == HTTPStatus.OK
    assert response.json() == MISSING_PARAMETER
    assert not UserUnlock.objects.exists()
    _assert_flagged_signature(
        player,
        "missing",
        action="awardachievement",
        achievement_id=ACHIEVEMENT_ID,
        hardcore=True,
        seconds_since_unlock=0,
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("params", "hardcore", "seconds_since_unlock"),
    [
        # The softcore signature cannot upgrade the unlock to hardcore.
        ({"h": "1", "v": V_AWARD_SOFTCORE}, True, 0),
        # `o` is signed, so a first-attempt signature cannot backdate the unlock.
        ({"h": "1", "o": SECONDS_SINCE_UNLOCK, "v": V_AWARD_HARDCORE}, True, SECONDS_SINCE_UNLOCK),
        ({"h": "0", "v": "0" * len(V_AWARD_SOFTCORE)}, False, 0),
        ({"h": "0", "v": "é"}, False, 0),
    ],
)
def test_award_with_a_wrong_v_is_rejected_and_flagged(
    client, player, achievement, params, hardcore, seconds_since_unlock
):
    response = _award(client, a=ACHIEVEMENT_ID, **params)

    assert response.json() == INVALID_V
    assert not UserUnlock.objects.exists()
    _assert_flagged_signature(
        player,
        "mismatch",
        action="awardachievement",
        achievement_id=ACHIEVEMENT_ID,
        hardcore=hardcore,
        seconds_since_unlock=seconds_since_unlock,
    )


@pytest.mark.django_db
def test_award_signed_for_another_user_is_rejected(client, player, achievement):
    v = award_validation_hash(ACHIEVEMENT_ID, "someone-else", True, 0)

    response = _award(client, a=ACHIEVEMENT_ID, h="1", v=v)

    assert response.json() == INVALID_V


@pytest.mark.django_db
@pytest.mark.parametrize(("name", "value"), [("h", "yes"), ("o", "-1"), ("o", "later")])
def test_award_rejects_malformed_signed_parameters(client, player, achievement, name, value):
    params = {"a": ACHIEVEMENT_ID, "h": "1", "v": V_AWARD_HARDCORE, name: value}

    response = _award(client, **params)

    assert response.json()["Code"] == "invalid_parameter"
    assert not UserUnlock.objects.exists()


# --- submitlbentry signature ---


@pytest.mark.django_db
@pytest.mark.parametrize(
    "params",
    [{"v": V_LBENTRY}, {"o": SECONDS_SINCE_COMPLETION, "v": V_LBENTRY_RETRY}],
)
def test_submit_with_rcheevos_signature_records_the_entry(client, player, leaderboard, params):
    response = _submit(client, i=LEADERBOARD_ID, s=SCORE, **params)

    assert response.json()["Success"] is True
    assert LeaderboardEntry.objects.get(user=player, leaderboard=leaderboard).score == SCORE
    assert not SuspiciousActivity.objects.exists()


@pytest.mark.django_db
def test_submit_without_v_is_rejected_and_flagged(client, player, leaderboard):
    response = _submit(client, i=LEADERBOARD_ID, s=SCORE)

    assert response.json() == MISSING_PARAMETER
    assert not LeaderboardEntry.objects.exists()
    _assert_flagged_signature(
        player,
        "missing",
        action="submitlbentry",
        leaderboard_id=LEADERBOARD_ID,
        score=SCORE,
        seconds_since_completion=0,
    )


@pytest.mark.django_db
def test_submit_with_a_wrong_v_is_rejected_and_flagged(client, player, leaderboard):
    # The signature of another score cannot carry this one.
    response = _submit(client, i=LEADERBOARD_ID, s=SCORE - 1, v=V_LBENTRY)

    assert response.json() == INVALID_V
    assert not LeaderboardEntry.objects.exists()
    _assert_flagged_signature(
        player,
        "mismatch",
        action="submitlbentry",
        leaderboard_id=LEADERBOARD_ID,
        score=SCORE - 1,
        seconds_since_completion=0,
    )


# A client looping on bad signatures.
REPEATED_BAD_SIGNATURES = 5


@pytest.mark.django_db
def test_repeated_bad_signatures_are_flagged_once_per_action_and_window(
    client, player, achievement, leaderboard
):
    for _ in range(REPEATED_BAD_SIGNATURES):
        assert _submit(client, i=LEADERBOARD_ID, s=SCORE).json() == MISSING_PARAMETER
        assert _award(client, a=ACHIEVEMENT_ID, h="1").json() == MISSING_PARAMETER

    actions = SuspiciousActivity.objects.filter(user=player).values_list(
        "detail__action", flat=True
    )
    assert sorted(actions) == ["awardachievement", "submitlbentry"]


# --- rate limit and unlock heuristics ---


def _achievements(game, author, count):
    return Achievement.objects.bulk_create(
        Achievement(
            game=game,
            author=author,
            title=f"Achievement {number}",
            description="d",
            points=1,
            mem_addr="0xH0001=1",
            status=Achievement.STATUS_OFFICIAL,
        )
        for number in range(count)
    )


def _signed_award(client, achievement, seconds_since_unlock=0):
    v = award_validation_hash(achievement.pk, PLAYER, False, seconds_since_unlock)
    params = {"a": achievement.pk, "h": "0", "v": v}
    if seconds_since_unlock:
        params["o"] = seconds_since_unlock
    return _award(client, **params)


def _kinds(user):
    return sorted(SuspiciousActivity.objects.filter(user=user).values_list("kind", flat=True))


TOO_MANY_UNLOCKS = {
    "Success": False,
    "Error": "Too many unlocks at once. The unlock will be retried.",
    "Status": HTTPStatus.TOO_MANY_REQUESTS,
}
# The acceptance scenario: a script firing a hundred unlocks within five seconds.
SCRIPTED_UNLOCKS = 100


@pytest.mark.django_db
def test_hundred_unlocks_at_once_are_throttled_and_flagged(client, player, game):
    achievements = _achievements(game, player, SCRIPTED_UNLOCKS)

    responses = [_signed_award(client, achievement) for achievement in achievements]

    accepted = responses[:AWARD_RATE_LIMIT]
    throttled = responses[AWARD_RATE_LIMIT:]
    assert all(response.json()["Success"] for response in accepted)
    assert {response.status_code for response in throttled} == {HTTPStatus.TOO_MANY_REQUESTS}
    assert all(response.json() == TOO_MANY_UNLOCKS for response in throttled)
    assert UserUnlock.objects.filter(user=player).count() == AWARD_RATE_LIMIT
    assert _kinds(player) == [
        SuspiciousActivity.Kind.RATE_LIMITED,
        SuspiciousActivity.Kind.UNLOCK_BURST,
    ]
    rate_limited = SuspiciousActivity.objects.get(kind=SuspiciousActivity.Kind.RATE_LIMITED)
    assert rate_limited.detail == {
        "limit": AWARD_RATE_LIMIT,
        "window_seconds": AWARD_RATE_WINDOW.total_seconds(),
    }
    burst = SuspiciousActivity.objects.get(kind=SuspiciousActivity.Kind.UNLOCK_BURST)
    assert burst.detail == {
        "game_id": game.pk,
        "unlocks": UNLOCK_BURST_THRESHOLD,
        "window_seconds": UNLOCK_BURST_WINDOW.total_seconds(),
    }


@pytest.mark.django_db
def test_rate_limit_counts_each_user_apart(client, player, game):
    other = User.objects.create_user(username="other", password="pw")
    cache.set(AWARD_RATE_KEY.format(user_id=other.pk), AWARD_RATE_LIMIT)
    (achievement,) = _achievements(game, player, 1)

    assert _signed_award(client, achievement).json()["Success"] is True


@pytest.mark.django_db
def test_rate_limit_lifts_when_the_window_ends(client, player, game):
    first, second = _achievements(game, player, 2)
    cache.set(AWARD_RATE_KEY.format(user_id=player.pk), AWARD_RATE_LIMIT)
    assert _signed_award(client, first).status_code == HTTPStatus.TOO_MANY_REQUESTS

    cache.delete(AWARD_RATE_KEY.format(user_id=player.pk))

    assert _signed_award(client, second).json()["Success"] is True


@pytest.mark.django_db
def test_rate_limit_window_recovers_a_counter_left_without_expiry(player):
    # The state Redis INCR leaves when the key expires between `incr`'s existence check and
    # the INCR itself: a counter with no expiry.
    key = AWARD_RATE_KEY.format(user_id=player.pk)
    cache.set(key, 0, timeout=None)

    award_rate_exceeded(player)

    redis = cache._cache.get_client(key)
    assert 0 < redis.ttl(cache.make_and_validate_key(key)) <= AWARD_RATE_WINDOW.total_seconds()


@pytest.mark.django_db
def test_unlocks_below_the_burst_threshold_are_not_flagged(client, player, game):
    for achievement in _achievements(game, player, UNLOCK_BURST_THRESHOLD - 1):
        _signed_award(client, achievement)

    assert not SuspiciousActivity.objects.exists()


@pytest.mark.django_db
def test_unlocks_dated_back_by_o_still_count_toward_a_burst(client, player, game):
    long_ago = int(UNLOCK_BURST_WINDOW.total_seconds()) + 1
    for achievement in _achievements(game, player, UNLOCK_BURST_THRESHOLD):
        _signed_award(client, achievement, seconds_since_unlock=long_ago)

    assert _kinds(player) == [SuspiciousActivity.Kind.UNLOCK_BURST]


@pytest.mark.django_db
def test_hardcore_unlocks_of_a_set_owned_in_softcore_count_toward_a_burst(client, player, game):
    achievements = _achievements(game, player, UNLOCK_BURST_THRESHOLD)
    UserUnlock.objects.bulk_create(
        UserUnlock(
            user=player,
            achievement=achievement,
            hardcore=False,
            unlocked_at=timezone.now() - UNLOCK_BURST_WINDOW,
        )
        for achievement in achievements
    )

    for achievement in achievements:
        v = award_validation_hash(achievement.pk, PLAYER, True, 0)
        assert _award(client, a=achievement.pk, h="1", v=v).json()["Success"] is True

    assert _kinds(player) == [SuspiciousActivity.Kind.UNLOCK_BURST]


@pytest.mark.django_db
def test_unlock_right_after_startsession_is_flagged(client, player, achievement):
    client.post(
        "/dorequest.php", {"r": "startsession", "u": PLAYER, "t": TOKEN, "g": achievement.game_id}
    )

    _award(client, a=ACHIEVEMENT_ID, h="1", v=V_AWARD_HARDCORE)
    # A retry of the recorded unlock is not flagged again.
    _award(client, a=ACHIEVEMENT_ID, h="1", v=V_AWARD_HARDCORE)

    activity = SuspiciousActivity.objects.get(user=player)
    assert activity.kind == SuspiciousActivity.Kind.EARLY_UNLOCK
    assert activity.detail["game_id"] == achievement.game_id
    assert activity.detail["achievement_id"] == ACHIEVEMENT_ID
    assert activity.detail["seconds_since_unlock"] == 0
    assert (
        0 <= activity.detail["seconds_after_session_start"] < (EARLY_UNLOCK_WINDOW.total_seconds())
    )


@pytest.mark.django_db
def test_unlock_well_into_the_session_is_not_flagged(client, player, achievement):
    PlayerGame.objects.create(
        user=player,
        game=achievement.game,
        session_started_at=timezone.now() - EARLY_UNLOCK_WINDOW,
    )

    _award(client, a=ACHIEVEMENT_ID, h="1", v=V_AWARD_HARDCORE)

    assert not SuspiciousActivity.objects.exists()


@pytest.mark.django_db
def test_unlock_dated_back_by_o_is_judged_by_its_arrival(client, player, achievement):
    PlayerGame.objects.create(user=player, game=achievement.game, session_started_at=timezone.now())
    a_day_ago = int(UNLOCK_MAX_AGE.total_seconds())
    v = award_validation_hash(ACHIEVEMENT_ID, PLAYER, True, a_day_ago)

    _award(client, a=ACHIEVEMENT_ID, h="1", o=a_day_ago, v=v)

    activity = SuspiciousActivity.objects.get(user=player)
    assert activity.kind == SuspiciousActivity.Kind.EARLY_UNLOCK
    assert activity.detail["seconds_since_unlock"] == a_day_ago


# --- admin ---


@pytest.mark.django_db
def test_admin_changelist_lists_and_filters_activities(admin_client, suspect):
    _flag(suspect, SuspiciousActivity.Kind.RATE_LIMITED)
    _flag(suspect, SuspiciousActivity.Kind.UNLOCK_BURST, game_id=1)

    response = admin_client.get(SUSPICIOUS_CHANGELIST_URL, {"kind__exact": "rate_limited"})

    assert response.status_code == HTTPStatus.OK
    listed = list(response.context["cl"].result_list)
    assert [activity.kind for activity in listed] == [SuspiciousActivity.Kind.RATE_LIMITED]
    assert set(response.context["action_form"].fields["action"].choices) >= {
        ("mark_legit", "Marcar atividades selecionadas como legítimas"),
        ("mark_cheater", "Marcar atividades selecionadas como trapaça"),
    }


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("action", "verdict"),
    [
        ("mark_legit", SuspiciousActivity.ReviewStatus.LEGIT),
        ("mark_cheater", SuspiciousActivity.ReviewStatus.CHEATER),
    ],
)
def test_admin_review_action_sets_the_verdict_reviewer_and_time(
    admin_client, admin_user, suspect, action, verdict
):
    selected = [_flag(suspect), _flag(suspect, SuspiciousActivity.Kind.EARLY_UNLOCK)]
    untouched = _flag(suspect, SuspiciousActivity.Kind.RATE_LIMITED)
    before = timezone.now()

    response = _run_review_action(admin_client, action, selected)

    assert response.status_code == HTTPStatus.FOUND
    for activity in selected:
        activity.refresh_from_db()
        assert activity.review_status == verdict
        assert activity.reviewed_by == admin_user
        assert activity.reviewed_at >= before
    untouched.refresh_from_db()
    assert untouched.review_status == SuspiciousActivity.ReviewStatus.PENDING
    assert untouched.reviewed_by is None
    assert untouched.reviewed_at is None


@pytest.mark.django_db
def test_admin_review_action_message_is_in_brazilian_portuguese(admin_client, suspect):
    response = admin_client.post(
        SUSPICIOUS_CHANGELIST_URL,
        {"action": "mark_cheater", "_selected_action": [_flag(suspect).pk]},
        follow=True,
    )

    messages = [str(message) for message in response.context["messages"]]
    assert messages == ["1 atividade revisada como “Trapaceiro”."]


@pytest.mark.django_db
def test_admin_cannot_add_activities(admin_client):
    response = admin_client.get(f"{SUSPICIOUS_CHANGELIST_URL}add/")

    assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.django_db
def test_admin_review_action_needs_change_permission(client, suspect):
    staff = User.objects.create_user(username="viewer", password="pw", is_staff=True)
    staff.user_permissions.add(Permission.objects.get(codename="view_suspiciousactivity"))
    client.force_login(staff)
    activity = _flag(suspect)

    _run_review_action(client, "mark_cheater", [activity])

    activity.refresh_from_db()
    assert activity.review_status == SuspiciousActivity.ReviewStatus.PENDING

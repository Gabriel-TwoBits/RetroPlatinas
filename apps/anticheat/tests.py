from datetime import timedelta
from http import HTTPStatus

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.utils import timezone

from apps.accounts.models import API_TOKEN_HEX_LENGTH
from apps.achievements.models import Achievement, UserUnlock
from apps.anticheat.detection import award_validation_hash, leaderboard_validation_hash
from apps.anticheat.models import SuspiciousActivity
from apps.api.handlers import API_TOKEN_LIFETIME, MAX_UINT32, UNLOCK_MAX_AGE
from apps.games.models import Console, Game
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


def _achievement(game, author, **fields):
    return Achievement.objects.create(
        game=game,
        author=author,
        title=f"Achievement {fields.get('pk', '')}",
        description="d",
        points=10,
        mem_addr="0xH0001=1",
        status=Achievement.STATUS_COMMUNITY,
        **fields,
    )


@pytest.fixture
def achievement(game, player):
    return _achievement(game, player, pk=ACHIEVEMENT_ID)


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


# --- admin ---


@pytest.mark.django_db
def test_admin_changelist_lists_and_filters_activities(admin_client, suspect):
    _flag(suspect, SuspiciousActivity.Kind.RATE_LIMITED)
    _flag(suspect, SuspiciousActivity.Kind.UNLOCK_BURST, game_id=1)

    response = admin_client.get(SUSPICIOUS_CHANGELIST_URL, {"kind__exact": "rate_limited"})

    assert response.status_code == 200
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

    assert response.status_code == 302
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

    assert response.status_code == 403


@pytest.mark.django_db
def test_admin_review_action_needs_change_permission(client, suspect):
    staff = User.objects.create_user(username="viewer", password="pw", is_staff=True)
    staff.user_permissions.add(Permission.objects.get(codename="view_suspiciousactivity"))
    client.force_login(staff)
    activity = _flag(suspect)

    _run_review_action(client, "mark_cheater", [activity])

    activity.refresh_from_db()
    assert activity.review_status == SuspiciousActivity.ReviewStatus.PENDING

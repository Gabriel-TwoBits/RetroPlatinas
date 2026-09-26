import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.utils import timezone

from apps.anticheat.models import SuspiciousActivity

User = get_user_model()

SUSPICIOUS_CHANGELIST_URL = "/admin/anticheat/suspiciousactivity/"


@pytest.fixture
def suspect(db):
    return User.objects.create_user(username="suspect", password="pw")


def _flag(user, kind=SuspiciousActivity.Kind.UNLOCK_BURST, **detail):
    return SuspiciousActivity.objects.create(user=user, kind=kind, detail=detail)


def _run_review_action(admin_client, action, activities):
    return admin_client.post(
        SUSPICIOUS_CHANGELIST_URL,
        {"action": action, "_selected_action": [activity.pk for activity in activities]},
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

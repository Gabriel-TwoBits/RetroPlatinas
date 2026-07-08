import pytest
from django.core.management import call_command
from django.db import IntegrityError

from apps.accounts.models import User
from apps.achievements.models import Achievement, CodeNote, UserUnlock
from apps.games.models import Console, Game


@pytest.fixture
def user():
    return User.objects.create_user(username="player", password="pw-test-123")


@pytest.fixture
def game():
    console = Console.objects.create(ra_id=12, name="PlayStation", short_name="PS1")
    return Game.objects.create(title="Crash Bandicoot", console=console)


@pytest.fixture
def achievement(game, user):
    return Achievement.objects.create(
        game=game,
        author=user,
        title="First Steps",
        description="Complete N. Sanity Beach",
        points=5,
        mem_addr="0xH001234=5",
        status=Achievement.STATUS_DRAFT,
    )


@pytest.mark.django_db
def test_achievement_creation(achievement):
    assert achievement.status == Achievement.STATUS_DRAFT
    assert achievement.flags == 5
    assert "First Steps" in str(achievement)


@pytest.mark.django_db
def test_achievement_status_choices():
    values = [c[0] for c in Achievement.STATUS_CHOICES]
    assert Achievement.STATUS_DRAFT in values
    assert Achievement.STATUS_COMMUNITY in values
    assert Achievement.STATUS_VERIFIED in values


@pytest.mark.django_db
def test_userunlock_creation(achievement, user):
    unlock = UserUnlock.objects.create(user=user, achievement=achievement, hardcore=False)
    assert not unlock.hardcore


@pytest.mark.django_db
def test_userunlock_unique_together(achievement, user):
    UserUnlock.objects.create(user=user, achievement=achievement, hardcore=False)
    with pytest.raises(IntegrityError):
        UserUnlock.objects.create(user=user, achievement=achievement, hardcore=False)


@pytest.mark.django_db
def test_codenote_creation(game, user):
    note = CodeNote.objects.create(game=game, author=user, address="0x001234", note="lives counter")
    assert str(note) == f"0x001234 ({game})"


@pytest.mark.django_db
def test_seed_crash1_code_notes_command():
    call_command("seed_crash1_code_notes", verbosity=0)
    notes = CodeNote.objects.filter(game__title="Crash Bandicoot")
    assert notes.count() == 108
    assert "N. Sanity Beach" in notes.get(address="0x619c5").note
    assert "Overworld" in notes.get(address="0x61994").note


@pytest.mark.django_db
def test_seed_crash1_code_notes_command_is_idempotent():
    call_command("seed_crash1_code_notes", verbosity=0)
    call_command("seed_crash1_code_notes", verbosity=0)
    assert CodeNote.objects.filter(game__title="Crash Bandicoot").count() == 108

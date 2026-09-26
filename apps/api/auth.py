from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()


def user_from_token(token: str) -> User | None:
    if not token:
        return None
    return User.objects.filter(
        api_token=token,
        api_token_expires_at__gt=timezone.now(),
        is_active=True,
    ).first()


def is_expired_token(username: str, token: str) -> bool:
    """Whether `token` was issued to the active user `username` and has since expired."""
    if not username or not token:
        return False
    return User.objects.filter(
        username=username,
        api_token=token,
        api_token_expires_at__lte=timezone.now(),
        is_active=True,
    ).exists()

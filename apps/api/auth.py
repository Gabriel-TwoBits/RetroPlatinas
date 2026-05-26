from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()


def user_from_token(token: str) -> User | None:
    if not token:
        return None
    return User.objects.filter(
        api_token=token,
        api_token_expires_at__gt=timezone.now(),
    ).first()

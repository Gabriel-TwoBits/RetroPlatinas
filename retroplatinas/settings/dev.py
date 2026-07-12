from .base import *  # noqa: F401, F403

DEBUG = True

ALLOWED_HOSTS = ["*"]

SECRET_KEY = SECRET_KEY or "dev-insecure-do-not-use-in-production-abc123"  # noqa: F405

INTERNAL_IPS = ["127.0.0.1"]

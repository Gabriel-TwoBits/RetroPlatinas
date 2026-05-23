from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    email = models.EmailField(unique=True)
    api_token = models.CharField(max_length=64, unique=True, null=True, blank=True)
    api_token_expires_at = models.DateTimeField(null=True, blank=True)
    softcore_points = models.IntegerField(default=0)
    hardcore_points = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

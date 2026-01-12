from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _


class User(AbstractUser):
    """
    Custom user keyed by Keycloak subject.
    The primary key is the Keycloak `sub`; we still keep username/email for convenience.
    """

    id = models.CharField(
        primary_key=True,
        max_length=128,
        help_text=_("Keycloak subject (sub)"),
    )

    # Keep username/email fields from AbstractUser; ensure they cannot be null.
    email = models.EmailField(_("email address"), blank=True)
    username = models.CharField(_("username"), max_length=150, blank=True)

    USERNAME_FIELD = "id"
    REQUIRED_FIELDS: list[str] = []

    def __str__(self) -> str:
        return self.username or self.id

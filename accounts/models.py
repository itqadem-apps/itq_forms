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


class Child(models.Model):
    id = models.CharField(max_length=255, primary_key=True)
    name = models.CharField(max_length=255)
    photo_id = models.CharField(max_length=255, null=True, blank=True)
    status = models.CharField(max_length=32, default="active")


class ChildGuardian(models.Model):
    id = models.CharField(max_length=255, primary_key=True)
    child = models.ForeignKey(Child, on_delete=models.CASCADE, related_name="guardians")
    user_id = models.CharField(max_length=128, db_index=True)
    status = models.CharField(max_length=32, default="active")
    role = models.CharField(max_length=64, blank=True)
    organization_id = models.CharField(max_length=128, null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["user_id", "child"], name="accounts_ch_user_id_2ae46f_idx"),
            models.Index(fields=["user_id", "status"], name="accounts_ch_user_id_97f11b_idx"),
        ]

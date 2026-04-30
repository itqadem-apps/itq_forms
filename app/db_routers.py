from django.conf import settings


class AclRouter:
    """Route pkg_auth ACL mirror models to the ``acl`` database.

    The ACL schema is owned by the source-of-truth service (itq_users);
    this service is Mode B and only reads it. When ``ACL_DATABASE_URL``
    is set, ``settings.DATABASES["acl"]`` is configured and we pin
    ``app_label="pkg_auth_acl"`` reads/writes there.

    For local dev / unit tests where the ACL DB isn't configured, fall
    back to ``default`` so ORM calls don't raise ConnectionDoesNotExist.
    The mirror models are ``managed=False``, so a missing schema in
    ``default`` will surface as a clear "relation does not exist" rather
    than a confusing routing error.
    """

    ACL_APP_LABEL = "pkg_auth_acl"
    ACL_DB_ALIAS = "acl"

    def _acl_target(self):
        return self.ACL_DB_ALIAS if self.ACL_DB_ALIAS in settings.DATABASES else None

    def db_for_read(self, model, **hints):
        if model._meta.app_label == self.ACL_APP_LABEL:
            return self._acl_target()
        return None

    def db_for_write(self, model, **hints):
        if model._meta.app_label == self.ACL_APP_LABEL:
            return self._acl_target()
        return None

    def allow_relation(self, obj1, obj2, **hints):
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label == self.ACL_APP_LABEL:
            return False
        if db == self.ACL_DB_ALIAS:
            return False
        return None

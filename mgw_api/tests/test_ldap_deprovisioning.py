from datetime import timedelta
from unittest.mock import patch

import ldap
from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from django.test import override_settings
from django.utils import timezone

from mgw_api.models import UserDeprovisionState


class FakeLDAPConnection:
    def __init__(self, existing_users=None, search_error=None):
        self.existing_users = set(existing_users or [])
        self.search_error = search_error
        self.search_filters = []

    def set_option(self, option, value):
        return None

    def simple_bind_s(self, *args):
        return None

    def search_s(self, search_root, scope, search_filter):
        if self.search_error:
            raise self.search_error
        self.search_filters.append(search_filter)
        for username in self.existing_users:
            if f"(cn={username})" == search_filter:
                return [(f"cn={username},{search_root}", {})]
        return []


LDAP_SETTINGS = {
    "AUTH_LDAP_SERVER_URI": "ldap://ldap.example.test",
    "AUTH_LDAP_BIND_DN": "",
    "AUTH_LDAP_BIND_PASSWORD": "",
    "LDAP_SEARCH_ROOT": "ou=users,dc=example,dc=test",
    "LDAP_USER_SEARCH_FILTER": "(cn=%(user)s)",
    "LDAP_DEPROVISION_GRACE_DAYS": 7,
    "LDAP_DEPROVISION_DISABLE_IMMEDIATELY": True,
    "LDAP_DEPROVISION_DELETE_AFTER_GRACE": False,
    "LDAP_DEPROVISION_NOTIFY_EMAIL": "ops@example.test",
    "LDAP_DEPROVISION_EXEMPT_STAFF": True,
    "LDAP_DEPROVISION_EXEMPT_USERNAMES": [],
    "DEFAULT_FROM_EMAIL": "mgwatch@example.test",
    "EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend",
}


@override_settings(**LDAP_SETTINGS)
class LDAPDeprovisioningTests(TestCase):
    def _run_command(self, connection):
        with patch(
            "mgw_api.management.commands.reconcile_ldap_users.ldap.initialize",
            return_value=connection,
        ):
            call_command("reconcile_ldap_users")

    def test_missing_ldap_user_is_disabled_tracked_and_notified(self):
        user = User.objects.create_user(username="missing", password="testpass123")

        self._run_command(FakeLDAPConnection(existing_users=[]))

        user.refresh_from_db()
        state = user.deprovision_state
        self.assertFalse(user.is_active)
        self.assertEqual(state.source, UserDeprovisionState.Source.LDAP)
        self.assertIsNotNone(state.first_missing_from_ldap_at)
        self.assertIsNotNone(state.disabled_at)
        self.assertEqual(
            state.deletion_due_at,
            state.first_missing_from_ldap_at + timedelta(days=7),
        )
        self.assertIsNotNone(state.notification_sent_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("missing", mail.outbox[0].body)

    def test_ldap_outage_does_not_mark_user_missing(self):
        user = User.objects.create_user(username="owner", password="testpass123")

        with patch(
            "mgw_api.management.commands.reconcile_ldap_users.ldap.initialize",
            return_value=FakeLDAPConnection(search_error=ldap.SERVER_DOWN("down")),
        ):
            with self.assertRaisesMessage(Exception, "LDAP search failed"):
                call_command("reconcile_ldap_users")

        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertFalse(UserDeprovisionState.objects.filter(user=user).exists())

    def test_reappearing_user_clears_pending_deletion_and_reactivates(self):
        user = User.objects.create_user(
            username="returned", password="testpass123", is_active=False
        )
        UserDeprovisionState.objects.create(
            user=user,
            first_missing_from_ldap_at=timezone.now() - timedelta(days=1),
            disabled_at=timezone.now() - timedelta(days=1),
            deletion_due_at=timezone.now() + timedelta(days=6),
        )

        self._run_command(FakeLDAPConnection(existing_users=["returned"]))

        user.refresh_from_db()
        state = user.deprovision_state
        self.assertTrue(user.is_active)
        self.assertIsNone(state.first_missing_from_ldap_at)
        self.assertIsNone(state.disabled_at)
        self.assertIsNone(state.deletion_due_at)
        self.assertIsNotNone(state.last_seen_in_ldap_at)

    @override_settings(LDAP_DEPROVISION_DELETE_AFTER_GRACE=True)
    def test_missing_user_is_deleted_after_grace_when_enabled(self):
        user = User.objects.create_user(username="expired", password="testpass123")
        UserDeprovisionState.objects.create(
            user=user,
            first_missing_from_ldap_at=timezone.now() - timedelta(days=8),
            deletion_due_at=timezone.now() - timedelta(days=1),
        )

        self._run_command(FakeLDAPConnection(existing_users=[]))

        self.assertFalse(User.objects.filter(username="expired").exists())

    def test_local_source_user_is_skipped(self):
        user = User.objects.create_user(username="local", password="testpass123")
        UserDeprovisionState.objects.create(
            user=user,
            source=UserDeprovisionState.Source.LOCAL,
        )

        self._run_command(FakeLDAPConnection(existing_users=[]))

        user.refresh_from_db()
        self.assertTrue(user.is_active)
        state = user.deprovision_state
        self.assertIsNone(state.first_missing_from_ldap_at)

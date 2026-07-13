from datetime import timedelta

import ldap
from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.utils import timezone
from ldap.filter import escape_filter_chars

from mgw_api.models import UserDeprovisionState


def _ldap_setting(name, default=None):
    return getattr(settings, name, default)


def _connect_to_ldap():
    uri = _ldap_setting("AUTH_LDAP_SERVER_URI", "")
    if not uri:
        raise CommandError("LDAP is not configured; LDAP_SERVER_URI is empty.")

    try:
        connection = ldap.initialize(uri)
        connection.set_option(ldap.OPT_REFERRALS, 0)
        bind_dn = _ldap_setting("AUTH_LDAP_BIND_DN", "")
        bind_password = _ldap_setting("AUTH_LDAP_BIND_PASSWORD", "")
        if bind_dn:
            connection.simple_bind_s(bind_dn, bind_password)
        else:
            connection.simple_bind_s()
        return connection
    except ldap.LDAPError as exc:
        raise CommandError(f"LDAP connection failed: {exc}") from exc


def _ldap_user_exists(connection, username):
    search_root = _ldap_setting("LDAP_SEARCH_ROOT")
    search_filter_template = _ldap_setting("LDAP_USER_SEARCH_FILTER", "(cn=%(user)s)")
    if not search_root:
        raise CommandError("LDAP_SEARCH_ROOT is required for LDAP reconciliation.")

    search_filter = search_filter_template % {
        "user": escape_filter_chars(username),
    }
    try:
        results = connection.search_s(search_root, ldap.SCOPE_SUBTREE, search_filter)
    except ldap.LDAPError as exc:
        raise CommandError(f"LDAP search failed for user {username}: {exc}") from exc
    return bool(results)


def _send_deprovision_notification(user, state):
    notify_email = _ldap_setting("LDAP_DEPROVISION_NOTIFY_EMAIL", "")
    if not notify_email or state.notification_sent_at:
        return False

    subject = f"MetagenomeWatch LDAP deprovisioning: {user.username}"
    body = (
        f"User {user.username} is no longer present in LDAP.\n\n"
        f"First missing: {state.first_missing_from_ldap_at}\n"
        f"Deletion due: {state.deletion_due_at}\n"
        f"Disabled: {state.disabled_at is not None}\n"
    )
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [notify_email])
    state.notification_sent_at = timezone.now()
    state.save(update_fields=["notification_sent_at"])
    return True


def _save_state(state, update_fields):
    if state.pk:
        state.save(update_fields=update_fields)
    else:
        state.save()


class Command(BaseCommand):
    help = "Reconcile local users against LDAP and handle deprovisioned accounts."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--username",
            action="append",
            dest="usernames",
            help="Limit reconciliation to one username. Can be passed more than once.",
        )
        parser.add_argument(
            "--include-staff",
            action="store_true",
            help="Include staff/superuser accounts even if they are normally exempt.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        now = timezone.now()
        grace_days = _ldap_setting("LDAP_DEPROVISION_GRACE_DAYS", 30)
        delete_after_grace = _ldap_setting("LDAP_DEPROVISION_DELETE_AFTER_GRACE", False)
        disable_immediately = _ldap_setting(
            "LDAP_DEPROVISION_DISABLE_IMMEDIATELY", True
        )
        exempt_staff = _ldap_setting("LDAP_DEPROVISION_EXEMPT_STAFF", True)
        exempt_usernames = set(_ldap_setting("LDAP_DEPROVISION_EXEMPT_USERNAMES", []))

        connection = _connect_to_ldap()
        users = User.objects.order_by("username")
        if options["usernames"]:
            users = users.filter(username__in=options["usernames"])

        checked = found = missing = disabled = deleted = notified = skipped = 0
        for user in users:
            if user.username in exempt_usernames:
                skipped += 1
                continue
            if (
                exempt_staff
                and not options["include_staff"]
                and (user.is_staff or user.is_superuser)
            ):
                skipped += 1
                continue

            try:
                state = user.deprovision_state
            except UserDeprovisionState.DoesNotExist:
                state = None

            if state and state.source == UserDeprovisionState.Source.LOCAL:
                skipped += 1
                continue

            checked += 1
            user_exists = _ldap_user_exists(connection, user.username)
            state = state or UserDeprovisionState(user=user)

            if user_exists:
                found += 1
                update_fields = [
                    "last_checked_at",
                    "last_seen_in_ldap_at",
                    "first_missing_from_ldap_at",
                    "deletion_due_at",
                    "last_error",
                ]
                state.last_checked_at = now
                state.last_seen_in_ldap_at = now
                state.first_missing_from_ldap_at = None
                state.deletion_due_at = None
                state.last_error = ""
                if state.disabled_at and not user.is_active and not dry_run:
                    user.is_active = True
                    user.save(update_fields=["is_active"])
                    state.disabled_at = None
                    update_fields.append("disabled_at")
                if not dry_run:
                    _save_state(state, update_fields)
                continue

            missing += 1
            first_missing = state.first_missing_from_ldap_at or now
            deletion_due = first_missing + timedelta(days=grace_days)
            should_disable = disable_immediately or now >= deletion_due
            should_delete = delete_after_grace and now >= deletion_due

            if not dry_run:
                state.last_checked_at = now
                state.first_missing_from_ldap_at = first_missing
                state.deletion_due_at = deletion_due
                state.last_error = ""
                update_fields = [
                    "last_checked_at",
                    "first_missing_from_ldap_at",
                    "deletion_due_at",
                    "last_error",
                ]
                if should_disable and user.is_active:
                    user.is_active = False
                    user.save(update_fields=["is_active"])
                    state.disabled_at = now
                    update_fields.append("disabled_at")
                    disabled += 1
                _save_state(state, update_fields)
                if _send_deprovision_notification(user, state):
                    notified += 1
                if should_delete:
                    user.delete()
                    deleted += 1
            else:
                if should_disable and user.is_active:
                    disabled += 1
                if should_delete:
                    deleted += 1

        self.stdout.write(
            self.style.SUCCESS(
                "LDAP reconciliation completed: "
                f"checked={checked} found={found} missing={missing} "
                f"disabled={disabled} deleted={deleted} notified={notified} "
                f"skipped={skipped}"
            )
        )

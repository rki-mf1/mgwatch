from datetime import timedelta

from axes.utils import reset
from django.contrib.auth.models import User
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse


@override_settings(
    AXES_ENABLED=True,
    AXES_FAILURE_LIMIT=2,
    AXES_COOLOFF_TIME=timedelta(minutes=30),
    AXES_LOCKOUT_PARAMETERS=[["username", "ip_address"]],
    AXES_RESET_ON_SUCCESS=True,
    AXES_HTTP_RESPONSE_CODE=429,
)
class LoginRateLimitingTests(TestCase):
    def setUp(self):
        reset()
        self.user = User.objects.create_user(
            username="limited-user", password="correct-password"
        )
        self.login_url = reverse("mgw_api:login")

    def tearDown(self):
        reset()

    def test_failed_login_attempts_lock_out_username_ip_pair(self):
        credentials = {
            "username": self.user.username,
            "password": "wrong-password",
        }

        self.client.post(self.login_url, credentials)
        self.client.post(self.login_url, credentials)

        response = self.client.post(
            self.login_url,
            {
                "username": self.user.username,
                "password": "correct-password",
            },
        )

        self.assertEqual(response.status_code, 429)

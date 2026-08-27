from django.test import SimpleTestCase

from mgw import settings as mgw_settings


class ProductionSecretGuardTests(SimpleTestCase):
    def test_flags_known_insecure_secret_values(self):
        reasons = mgw_settings.unsafe_production_secret_reasons(
            "django-insecure-em&y0o^!@ha-kujz4qch11-a*qy8t3peg8@%+=(_+-bnwzr2%z",
            "mongodb://root:example1@mgwatch-mongodb:27017/",
            "example1",
        )

        self.assertEqual(len(reasons), 3)

    def test_allows_non_placeholder_values(self):
        reasons = mgw_settings.unsafe_production_secret_reasons(
            "prod-secret-with-enough-random-looking-characters-0123456789",
            "mongodb://root:prod-mongo-password-0123456789@mgwatch-mongodb:27017/",
            "prod-postgres-password-0123456789",
        )

        self.assertEqual(reasons, [])

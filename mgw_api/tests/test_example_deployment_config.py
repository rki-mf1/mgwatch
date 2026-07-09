from pathlib import Path
from unittest import TestCase

EXAMPLE_CONFIG_DIR = Path(__file__).resolve().parents[2] / "example-config"


class ExampleDeploymentConfigTests(TestCase):
    def test_only_proxy_service_publishes_host_ports(self):
        compose_text = (EXAMPLE_CONFIG_DIR / "compose.prod.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("mgwatch-proxy:", compose_text)
        self.assertEqual(compose_text.count("\n    ports:"), 1)
        self.assertIn(
            "- ${PUBLIC_BIND_ADDRESS}:${PUBLIC_HTTP_PORT}:8000",
            compose_text,
        )
        self.assertNotIn("27017:27017", compose_text)
        self.assertNotIn("6379:6379", compose_text)

    def test_example_env_files_require_replacement_secrets(self):
        env_text = (EXAMPLE_CONFIG_DIR / ".env.example").read_text(encoding="utf-8")
        vars_text = (EXAMPLE_CONFIG_DIR / "vars.env.example").read_text(
            encoding="utf-8"
        )
        combined = f"{env_text}\n{vars_text}"

        self.assertIn("CHANGE_ME_LONG_RANDOM_DJANGO_SECRET_KEY", combined)
        self.assertIn("CHANGE_ME_LONG_RANDOM_MONGODB_PASSWORD", combined)
        self.assertIn("DEBUG=False", vars_text)
        self.assertNotIn("django-insecure-", combined)
        self.assertNotIn("ALLOWED_HOSTS='*'", combined)
        self.assertNotIn("DEBUG=True", combined)
        self.assertNotIn("example1", combined)

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
        self.assertNotIn("5432:5432", compose_text)
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
        self.assertIn("CHANGE_ME_LONG_RANDOM_POSTGRES_PASSWORD", combined)
        self.assertIn("DEBUG=False", vars_text)
        self.assertNotIn("django-insecure-", combined)
        self.assertNotIn("ALLOWED_HOSTS='*'", combined)
        self.assertNotIn("DEBUG=True", combined)
        self.assertNotIn("example1", combined)

    def test_production_compose_includes_runtime_hardening_and_healthchecks(self):
        compose_text = (EXAMPLE_CONFIG_DIR / "compose.prod.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            'user: "${MGWATCH_UID:-1000}:${MGWATCH_GID:-1000}"',
            compose_text,
        )
        self.assertIn("no-new-privileges:true", compose_text)
        self.assertIn("cap_drop:", compose_text)
        self.assertIn("read_only: true", compose_text)
        self.assertEqual(compose_text.count("healthcheck:"), 8)

    def test_production_compose_runs_celery_beat_for_recurring_work(self):
        compose_text = (EXAMPLE_CONFIG_DIR / "compose.prod.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("mgwatch-celery-beat:", compose_text)
        self.assertIn("celery -A mgw beat --loglevel INFO", compose_text)
        self.assertIn("--queues maintenance,indexing,watches", compose_text)
        self.assertNotIn("/var/spool/cron", compose_text)

    def test_production_nginx_template_rate_limits_login(self):
        nginx_text = (
            EXAMPLE_CONFIG_DIR / "nginx-templates" / "mgwatch.conf.template"
        ).read_text(encoding="utf-8")
        env_text = (EXAMPLE_CONFIG_DIR / ".env.example").read_text(encoding="utf-8")
        compose_text = (EXAMPLE_CONFIG_DIR / "compose.prod.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("limit_req_zone $binary_remote_addr", nginx_text)
        self.assertIn("zone=mgwatch_login:10m", nginx_text)
        self.assertIn("rate=${NGINX_LOGIN_RATE_LIMIT}", nginx_text)
        self.assertIn("location = /login/", nginx_text)
        self.assertIn(
            "limit_req zone=mgwatch_login burst=${NGINX_LOGIN_RATE_BURST} nodelay;",
            nginx_text,
        )
        self.assertIn("NGINX_LOGIN_RATE_LIMIT=10r/m", env_text)
        self.assertIn("NGINX_LOGIN_RATE_BURST=5", env_text)
        self.assertIn(
            "NGINX_LOGIN_RATE_LIMIT=${NGINX_LOGIN_RATE_LIMIT:-10r/m}",
            compose_text,
        )
        self.assertIn(
            "NGINX_LOGIN_RATE_BURST=${NGINX_LOGIN_RATE_BURST:-5}",
            compose_text,
        )

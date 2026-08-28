from django.conf import settings
from django.test import SimpleTestCase


class LoggingConfigurationTests(SimpleTestCase):
    def test_celery_task_header_generation_debug_output_is_suppressed(self):
        logger_config = settings.LOGGING["loggers"]["celery.utils.functional"]

        self.assertEqual(logger_config["level"], "INFO")

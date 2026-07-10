import shutil

from django.conf import settings
from django.contrib.auth.models import User
from django.db.models.signals import post_delete
from django.dispatch import receiver

from mgw.settings import LOGGER


@receiver(post_delete, sender=User)
def delete_user_directory(sender, instance, **kwargs):
    LOGGER.info(f"Deleting user directory {instance.id}")
    user_directory = settings.MEDIA_ROOT / f"user_{instance.id}"
    if user_directory.exists():
        shutil.rmtree(user_directory)

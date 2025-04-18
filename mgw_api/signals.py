# mgw_api/signals.py

import os
import shutil

from django.contrib.auth.models import User
from django.db.models.signals import post_delete
from django.dispatch import receiver

from mgw.settings import LOGGER


@receiver(post_delete, sender=User)
def delete_user_directory(sender, instance, **kwargs):
    LOGGER.info(f"Deleting user directory {instance.id}")
    user_directory = f"user_{instance.id}"
    if os.path.exists(user_directory):
        shutil.rmtree(user_directory)

"""Create the single sign-in user from ADMIN_USERNAME / ADMIN_PASSWORD if no user exists yet."""
import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    def handle(self, *args, **opts):
        User = get_user_model()
        if User.objects.exists():
            self.stdout.write("A user already exists; nothing to do.")
            return
        username = os.environ.get("ADMIN_USERNAME")
        password = os.environ.get("ADMIN_PASSWORD")
        if not (username and password):
            self.stdout.write("ADMIN_USERNAME / ADMIN_PASSWORD not set; no user created.")
            return
        User.objects.create_superuser(username=username, password=password)
        self.stdout.write(f"Created user {username}.")

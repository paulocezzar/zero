"""Create the single sign-in user from ADMIN_USERNAME / ADMIN_PASSWORD if no user exists yet.

If you are locked out: set ADMIN_RESET_PASSWORD=1 (and a new ADMIN_PASSWORD) in the service's
environment, let it redeploy, sign in, then remove ADMIN_RESET_PASSWORD again.
"""
import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    def handle(self, *args, **opts):
        User = get_user_model()
        username = os.environ.get("ADMIN_USERNAME")
        password = os.environ.get("ADMIN_PASSWORD")
        if os.environ.get("ADMIN_RESET_PASSWORD") == "1" and username and password:
            user = User.objects.filter(username=username).first()
            if user:
                user.set_password(password)
                user.save(update_fields=["password"])
                self.stdout.write(f"Password reset for {username}. Remove ADMIN_RESET_PASSWORD from the environment now.")
                return
        if User.objects.exists():
            self.stdout.write("A user already exists; nothing to do.")
            return
        if not (username and password):
            self.stdout.write("ADMIN_USERNAME / ADMIN_PASSWORD not set; no user created.")
            return
        User.objects.create_superuser(username=username, password=password)
        self.stdout.write(f"Created user {username}.")

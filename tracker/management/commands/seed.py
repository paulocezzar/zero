"""Load the starting debts and budget lines from tracker/fixtures/seed.json."""
import json
from pathlib import Path

from django.core.management.base import BaseCommand

from tracker.models import BudgetLine, Debt


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("--if-empty", action="store_true", help="Only seed when there are no debts yet")
        parser.add_argument("--user", default=None, help="Username to seed for (default: ADMIN_USERNAME or the first user)")

    def handle(self, *args, **opts):
        import os
        from django.contrib.auth import get_user_model
        User = get_user_model()
        name = opts["user"] or os.environ.get("ADMIN_USERNAME")
        user = User.objects.filter(username=name).first() if name else User.objects.order_by("id").first()
        if not user:
            self.stdout.write("No user to seed for.")
            return
        if opts["if_empty"] and Debt.objects.filter(owner=user).exists():
            self.stdout.write("Debts already present; not seeding.")
            return
        data = json.loads((Path(__file__).resolve().parents[2] / "fixtures" / "seed.json").read_text())
        for i, d in enumerate(data["debts"]):
            Debt.objects.create(owner=user, priority=i, **d)
        for b in data["budget"]:
            BudgetLine.objects.create(owner=user, **b)
        self.stdout.write(f"Seeded {len(data['debts'])} debts and {len(data['budget'])} budget lines.")

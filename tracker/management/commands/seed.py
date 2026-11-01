"""Load the starting debts and budget lines from tracker/fixtures/seed.json."""
import json
from pathlib import Path

from django.core.management.base import BaseCommand

from tracker.models import BudgetLine, Debt


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("--if-empty", action="store_true", help="Only seed when there are no debts yet")

    def handle(self, *args, **opts):
        if opts["if_empty"] and Debt.objects.exists():
            self.stdout.write("Debts already present; not seeding.")
            return
        data = json.loads((Path(__file__).resolve().parents[2] / "fixtures" / "seed.json").read_text())
        for i, d in enumerate(data["debts"]):
            Debt.objects.create(priority=i, **d)
        for b in data["budget"]:
            BudgetLine.objects.create(**b)
        self.stdout.write(f"Seeded {len(data['debts'])} debts and {len(data['budget'])} budget lines.")

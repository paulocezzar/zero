"""One-off data updates applied at deploy time. Each update has an id; applied ids are recorded so it runs once.

Usage: python manage.py apply_updates   (reads tracker/fixtures/updates.json)
"""
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from tracker.models import BudgetLine, Debt, Payment, SettlementOffer
from tracker.views import record_snapshot


class Command(BaseCommand):
    help = "Apply pending one-off data updates from tracker/fixtures/updates.json (idempotent)."

    def handle(self, *args, **opts):
        path = Path(__file__).resolve().parents[2] / "fixtures" / "updates.json"
        if not path.exists():
            self.stdout.write("no updates file")
            return
        spec = json.loads(path.read_text())
        User = get_user_model()
        for up in spec.get("updates", []):
            user = User.objects.filter(username=up["user"]).first()
            if not user:
                self.stdout.write(f"{up['id']}: user not found, skipped")
                continue
            # idempotency marker: a SettlementOffer/Debt note or payment note carrying the update id
            if Debt.objects.filter(owner=user, note__contains=f"[{up['id']}]").exists() or Payment.objects.filter(debt__owner=user, note__contains=f"[{up['id']}]").exists():
                self.stdout.write(f"{up['id']}: already applied")
                continue
            with transaction.atomic():
                self.apply(user, up)
                record_snapshot(user)
            self.stdout.write(f"{up['id']}: applied")

    def apply(self, user, up):
        tag = f"[{up['id']}]"
        for e in up.get("edit_debts", []):
            d = Debt.objects.filter(owner=user, name__icontains=e["match"], closed=False).first()
            if not d:
                continue
            for k, v in e.get("set", {}).items():
                if k in ("balance", "monthly", "apr"):
                    v = Decimal(str(v))
                if k == "promo_until" and v:
                    v = date.fromisoformat(v)
                setattr(d, k, v)
            d.note = (e.get("note") or d.note or "") + f" {tag}"
            d.save()
        for n in up.get("new_debts", []):
            if Debt.objects.filter(owner=user, name=n["name"]).exists():
                continue
            top = Debt.objects.filter(owner=user).order_by("-priority").first()
            Debt.objects.create(owner=user, name=n["name"], kind=n.get("kind", "card"), balance=Decimal(str(n["balance"])), starting_balance=Decimal(str(n["balance"])),
                                monthly=Decimal(str(n.get("monthly", 0))), apr=Decimal(str(n.get("apr", 0))), promo_until=date.fromisoformat(n["promo_until"]) if n.get("promo_until") else None,
                                pay_day=n.get("pay_day", 1), priority=(top.priority + 1) if top else 0, note=(n.get("note") or "") + f" {tag}")
        for s in up.get("settle", []):
            d = Debt.objects.filter(owner=user, name__icontains=s["match"], closed=False).first()
            if not d:
                continue
            amt = Decimal(str(s["amount"]))
            SettlementOffer.objects.create(debt=d, date=date.fromisoformat(s["date"]), amount=amt, status="paid", note=s.get("note", ""))
            Payment.objects.create(debt=d, date=date.fromisoformat(s["date"]), amount=amt, note=f"settlement {tag}")
            d.balance = Decimal("0")
            d.closed = True
            d.note = (d.note or "") + f" settled {s['date']} {tag}"
            d.save()
        for b in up.get("edit_budget", []):
            line = BudgetLine.objects.filter(owner=user, item__icontains=b["match"]).first()
            if not line:
                continue
            for k, v in b.get("set", {}).items():
                setattr(line, k, Decimal(str(v)) if k == "amount" else v)
            line.save()
        for b in up.get("new_budget", []):
            if BudgetLine.objects.filter(owner=user, item=b["item"]).exists():
                continue
            BudgetLine.objects.create(owner=user, item=b["item"], group=b.get("group", "everyday"), category=b.get("category", "other"), amount=Decimal(str(b["amount"])), pay_day=b.get("pay_day"), note=b.get("note", ""))

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import BudgetLine, Debt, Payment


class LedgerTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("p", password="x" * 12)
        self.d = Debt.objects.create(name="Aqua", kind="card", balance=Decimal("1000"), monthly=Decimal("100"), apr=Decimal("30"), pay_day=3, priority=0)
        self.v = Debt.objects.create(name="Vanda", kind="family", balance=Decimal("500"), monthly=Decimal("50"), priority=1)
        BudgetLine.objects.create(item="Pay", group="income", amount=Decimal("3000"))
        BudgetLine.objects.create(item="Rent", group="home", amount=Decimal("-1400"))

    def test_login_required_everywhere(self):
        for name in ["overview", "debts", "payments", "month", "budget", "projection", "debt_new"]:
            r = self.client.get(reverse(name))
            self.assertEqual(r.status_code, 302, name)
            self.assertIn("/login/", r["Location"])
        for name in ["manifest", "icon", "sw"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_pages_render(self):
        self.client.force_login(self.user)
        for name in ["overview", "debts", "payments", "month", "budget", "projection", "debt_new"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        self.assertEqual(self.client.get(reverse("debt_edit", args=[self.d.pk])).status_code, 200)

    def test_payment_reduces_balance_and_undo_restores(self):
        self.client.force_login(self.user)
        r = self.client.post(reverse("payments"), {"date": date.today(), "debt": self.d.pk, "amount": "250", "note": "deposit"})
        self.assertEqual(r.status_code, 302)
        self.d.refresh_from_db()
        self.assertEqual(self.d.balance, Decimal("750"))
        p = Payment.objects.get()
        self.client.post(reverse("payment_undo", args=[p.pk]))
        self.d.refresh_from_db()
        self.assertEqual(self.d.balance, Decimal("1000"))

    def test_month_checkin_computes_left_over(self):
        self.client.force_login(self.user)
        self.client.post(reverse("month"), {"month": "2026-11-01", "income": "3000", "extra_income": "100", "everyday": "800", "note": ""})
        from .models import MonthCheckin
        m = MonthCheckin.objects.get()
        # 3000 + 100 - 1400 - (100 + 50) - 800
        self.assertEqual(m.left_over, Decimal("750"))

    def test_projection_interest_and_order(self):
        from . import projection
        res = projection.simulate([self.d, self.v], start=date(2026, 11, 1), extra=Decimal("300"), extra_from=date(2027, 1, 1))
        self.assertTrue(res.all_clear)
        aqua = res.debts[0]
        self.assertGreater(aqua.interest, 0)
        self.assertLess(aqua.clear, res.debts[1].clear)
        base = projection.simulate([self.d, self.v], start=date(2026, 11, 1), planned=False)
        self.assertGreater(base.debts[0].clear, aqua.clear)

    def test_debt_move(self):
        self.client.force_login(self.user)
        self.client.post(reverse("debt_move", args=[self.v.pk, "up"]))
        self.assertEqual(list(Debt.objects.values_list("name", flat=True)), ["Vanda", "Aqua"])

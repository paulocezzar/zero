from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import BudgetLine, Debt, Payment


class LedgerTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("p", password="x" * 12)
        self.other = get_user_model().objects.create_user("q", password="y" * 12)
        Debt.objects.create(owner=self.other, name="Someone else's", balance=Decimal("999"), monthly=Decimal("9"))
        self.d = Debt.objects.create(owner=self.user, name="Aqua", kind="card", balance=Decimal("1000"), monthly=Decimal("100"), apr=Decimal("30"), pay_day=3, priority=0)
        self.v = Debt.objects.create(owner=self.user, name="Vanda", kind="family", balance=Decimal("500"), monthly=Decimal("50"), priority=1)
        BudgetLine.objects.create(owner=self.user, item="Pay", group="income", amount=Decimal("3000"))
        BudgetLine.objects.create(owner=self.user, item="Rent", group="home", amount=Decimal("-1400"))

    def test_login_required_everywhere(self):
        for name in ["overview", "debts", "payments", "month", "budget", "projection", "debt_new"]:
            r = self.client.get(reverse(name))
            self.assertEqual(r.status_code, 302, name)
            self.assertIn("/login/", r["Location"])
        for name in ["manifest", "icon", "sw"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_pages_render(self):
        self.client.force_login(self.user)
        for name in ["overview", "debts", "payments", "month", "budget", "projection", "debt_new", "profile"]:
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
        m = MonthCheckin.objects.get(owner=self.user)
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
        self.assertEqual(list(Debt.objects.filter(owner=self.user).values_list("name", flat=True)), ["Vanda", "Aqua"])

    def test_users_cannot_see_each_other(self):
        self.client.force_login(self.user)
        r = self.client.get(reverse("debts"))
        self.assertNotContains(r, "Someone else")
        other = Debt.objects.get(owner=self.other)
        self.assertEqual(self.client.get(reverse("debt_edit", args=[other.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("quick_pay", args=[other.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("overview")).context["total"], Decimal("1500"))

    def test_signup_gated(self):
        self.assertEqual(self.client.get(reverse("signup")).status_code, 404)
        with self.settings(ALLOW_SIGNUP=True):
            self.assertEqual(self.client.get(reverse("signup")).status_code, 200)
            r = self.client.post(reverse("signup"), {"username": "newperson", "password1": "a-long-password-1", "password2": "a-long-password-1"})
            self.assertEqual(r.status_code, 302)
            self.assertEqual(self.client.get(reverse("debts")).status_code, 200)

    def test_quick_pay_once_per_month(self):
        self.client.force_login(self.user)
        self.client.post(reverse("quick_pay", args=[self.d.pk]))
        self.client.post(reverse("quick_pay", args=[self.d.pk]))
        self.d.refresh_from_db()
        self.assertEqual(self.d.balance, Decimal("900"))
        self.assertEqual(Payment.objects.count(), 1)
        self.assertNotContains(self.client.get(reverse("overview")), "quick_pay/%d/" % self.d.pk)

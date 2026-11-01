from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from django.core.files.uploadedfile import SimpleUploadedFile

from . import spending
from .models import BudgetLine, Debt, MonthCheckin, Outgoing, Payment


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
        for name in ["overview", "debts", "payments", "month", "budget", "projection", "debt_new", "profile", "spending", "import"]:
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


STARLING = """Date,Counter Party,Reference,Type,Amount (GBP),Balance (GBP),Spending Category,Notes
03/10/2026,THE NEWT,SALARY,FASTER PAYMENT,3304.00,3500.00,INCOME,
04/10/2026,Tesco Stores 1234,TESCO,CONTACTLESS,-42.50,3457.50,GROCERIES,
05/10/2026,Amazon,AMZN Mktp UK,CONTACTLESS,-19.99,3437.51,SHOPPING,
06/10/2026,Aqua,card payment,DIRECT DEBIT,-200.00,3237.51,PAYMENTS,
07/10/2026,Greggs,,CONTACTLESS,-3.20,3234.31,EATING OUT,
"""

AQUA = """Transaction Date,Posting Date,Description,Card,Amount
12/10/2026,13/10/2026,SAINSBURYS S/MKTS,****1234,38.10
14/10/2026,15/10/2026,PAYMENT RECEIVED - THANK YOU,****1234,-200.00
15/10/2026,16/10/2026,SHELL WINCANTON,****1234,55.00
"""


class SpendingTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("p", password="x" * 12)
        BudgetLine.objects.create(owner=self.user, item="Pay", group="income", amount=Decimal("3000"), category="other")
        BudgetLine.objects.create(owner=self.user, item="Groceries", group="everyday", amount=Decimal("-300"), category="groceries")
        BudgetLine.objects.create(owner=self.user, item="Eating out", group="everyday", amount=Decimal("-60"), category="eating")
        self.client.force_login(self.user)

    def test_categoriser(self):
        self.assertEqual(spending.categorise("TESCO STORES 1234"), "groceries")
        self.assertEqual(spending.categorise("AMZN Mktp UK"), "amazon")
        self.assertEqual(spending.categorise("SHELL WINCANTON"), "car")
        self.assertEqual(spending.categorise("Something odd"), "other")
        self.assertTrue(spending.is_skip("Aqua card payment DIRECT DEBIT"))
        self.assertTrue(spending.is_skip("PRA GROUP"))

    def test_parse_starling_drops_income_and_flags_debt_payment(self):
        source, rows = spending.parse(STARLING.encode(), self.user.id)
        self.assertEqual(source, "starling")
        self.assertEqual(len(rows), 4)
        by = {r["desc"]: r for r in rows}
        self.assertEqual(by["Tesco Stores 1234"]["category"], "groceries")
        self.assertEqual(by["Tesco Stores 1234"]["amount"], Decimal("42.50"))
        self.assertTrue(by["Aqua"]["skip"])
        self.assertEqual(by["Greggs"]["category"], "eating")

    def test_parse_aqua_positive_is_spend(self):
        source, rows = spending.parse(AQUA.encode(), self.user.id)
        self.assertEqual(source, "aqua")
        self.assertEqual([r["amount"] for r in rows], [Decimal("55.00"), Decimal("38.10")])
        self.assertEqual(rows[1]["category"], "groceries")

    def test_log_and_rails(self):
        r = self.client.post(reverse("spending"), {"date": date.today(), "amount": "45.00", "category": "groceries", "merchant": "Lidl", "note": ""})
        self.assertEqual(r.status_code, 302)
        r = self.client.get(reverse("spending"))
        self.assertContains(r, "Lidl")
        rails = {x["key"]: x for x in r.context["rails"]}
        self.assertEqual(rails["groceries"]["spent"], Decimal("45.00"))
        self.assertEqual(rails["groceries"]["left"], Decimal("255.00"))
        self.assertEqual(r.context["total"], Decimal("45.00"))

    def test_import_flow_dedupes(self):
        f = SimpleUploadedFile("starling.csv", STARLING.encode(), content_type="text/csv")
        r = self.client.post(reverse("import"), {"statement": f})
        self.assertRedirects(r, reverse("import_review"))
        r = self.client.get(reverse("import_review"))
        self.assertContains(r, "Tesco Stores 1234")
        data = {"stage": "confirm"}
        for i, row in enumerate(self.client.session["import_rows"]):
            data[f"cat-{i}"] = row["category"]
            if row["skip"]:
                data[f"skip-{i}"] = "1"
        r = self.client.post(reverse("import"), data)
        self.assertRedirects(r, reverse("spending"))
        self.assertEqual(Outgoing.objects.filter(owner=self.user).count(), 3)  # Aqua payment skipped
        self.assertEqual(Outgoing.objects.get(merchant="Tesco Stores 1234").source, "starling")
        # second import of the same file adds nothing
        f = SimpleUploadedFile("starling.csv", STARLING.encode(), content_type="text/csv")
        self.client.post(reverse("import"), {"statement": f})
        self.assertTrue(all(row["seen"] for row in self.client.session["import_rows"] if not row["skip"]))
        data = {"stage": "confirm"} | {f"skip-{i}": "1" for i, row in enumerate(self.client.session["import_rows"]) if row["skip"]}
        self.client.post(reverse("import"), data)
        self.assertEqual(Outgoing.objects.filter(owner=self.user).count(), 3)

    def test_checkin_everyday_prefilled_from_spending(self):
        Outgoing.objects.create(owner=self.user, date=date.today(), amount=Decimal("80"), category="groceries")
        r = self.client.get(reverse("month"))
        self.assertEqual(r.context["form"].initial["everyday"], Decimal("80"))
        r = self.client.post(reverse("month"), {"month": date.today().replace(day=1), "income": "3000", "extra_income": "0", "everyday": "", "note": ""})
        self.assertEqual(r.status_code, 302)
        m = MonthCheckin.objects.get(owner=self.user)
        self.assertEqual(m.everyday, Decimal("80"))

    def test_overview_shows_spent(self):
        Outgoing.objects.create(owner=self.user, date=date.today(), amount=Decimal("12.34"), category="eating")
        r = self.client.get(reverse("overview"))
        self.assertContains(r, "Spent this month")
        self.assertEqual(r.context["spent"], Decimal("12.34"))

    def test_other_user_cannot_see_or_delete(self):
        o = Outgoing.objects.create(owner=self.user, date=date.today(), amount=Decimal("5"), category="other", merchant="Mine")
        other = get_user_model().objects.create_user("q", password="y" * 12)
        self.client.force_login(other)
        self.assertNotContains(self.client.get(reverse("spending")), "Mine")
        self.assertEqual(self.client.post(reverse("outgoing_delete", args=[o.pk])).status_code, 404)

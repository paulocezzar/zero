from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from django.core.files.uploadedfile import SimpleUploadedFile

from . import spending
from .models import BudgetLine, CalendarToken, Consent, Debt, LoginAttempt, MonthCheckin, Outgoing, Payment, SettlementOffer, Snapshot


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
            r = self.client.post(reverse("signup"), {"username": "newperson", "password1": "a-long-password-1", "password2": "a-long-password-1", "agree": "on"})
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
        Debt.objects.create(owner=self.user, name="A", balance=Decimal("100"), monthly=Decimal("10"))
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


class MomentumTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("p", password="x" * 12)
        self.a = Debt.objects.create(owner=self.user, name="A", kind="collector", balance=Decimal("300"), monthly=Decimal("30"), pay_day=date.today().day, priority=0)
        self.b = Debt.objects.create(owner=self.user, name="B", kind="collector", balance=Decimal("500"), monthly=Decimal("25"), pay_day=date.today().day, priority=1)
        BudgetLine.objects.create(owner=self.user, item="Rent", group="home", amount=Decimal("-1400"), pay_day=1)
        self.client.force_login(self.user)

    def test_due_grouped_and_paid_all(self):
        r = self.client.get(reverse("overview"))
        self.assertEqual(len(r.context["groups"]), 1)
        self.assertEqual(r.context["groups"][0]["total"], Decimal("55"))
        self.assertContains(r, "Paid all 2")
        r = self.client.post(reverse("quick_pay_all"), {"ids": [self.a.pk, self.b.pk]})
        self.assertRedirects(r, reverse("overview"))
        self.a.refresh_from_db(); self.b.refresh_from_db()
        self.assertEqual((self.a.balance, self.b.balance), (Decimal("270"), Decimal("475")))
        self.assertEqual(Payment.objects.count(), 2)
        self.client.post(reverse("quick_pay_all"), {"ids": [self.a.pk, self.b.pk]})
        self.assertEqual(Payment.objects.count(), 2)  # once a month only
        r = self.client.get(reverse("overview"))
        self.assertEqual(r.context["streak"], 1)
        self.assertEqual(r.context["next_win"]["debt"], self.a)

    def test_snapshot_recorded_once_per_day(self):
        self.client.post(reverse("quick_pay", args=[self.a.pk]))
        self.client.post(reverse("payments"), {"date": date.today(), "debt": self.b.pk, "amount": "100", "note": ""})
        snaps = Snapshot.objects.filter(owner=self.user)
        self.assertEqual(snaps.count(), 1)
        self.assertEqual(snaps.first().total, Decimal("670"))
        self.assertIsNotNone(snaps.first().clear_month)

    def test_calendar_feed_without_login(self):
        self.client.get(reverse("profile"))
        tok = CalendarToken.objects.get(owner=self.user).token
        self.client.logout()
        r = self.client.get(reverse("calendar_feed", args=[tok]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "text/calendar; charset=utf-8")
        body = r.content.decode()
        self.assertIn("SUMMARY:£30.00 A", body)
        self.assertIn("SUMMARY:£1400.00 Rent", body)
        self.assertIn("TRIGGER:-P1D", body)
        self.assertEqual(self.client.get(reverse("calendar_feed", args=["nope"])).status_code, 404)


class PlanAndSettleTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("p", password="x" * 12)
        self.card = Debt.objects.create(owner=self.user, name="Card", kind="card", balance=Decimal("6000"), monthly=Decimal("250"), apr=Decimal("27.9"), promo_until=date.today().replace(day=1) + timedelta(days=800), priority=0)
        self.col = Debt.objects.create(owner=self.user, name="Collector", kind="collector", balance=Decimal("1000"), monthly=Decimal("25"), priority=1)
        self.client.force_login(self.user)

    def test_promo_means_no_interest_until_date(self):
        from tracker import projection
        r = projection.simulate([self.card], start=date.today().replace(day=1), planned=False)
        self.assertEqual(r.debts[0].interest, Decimal("0"))  # 6000/250 = 24 months, inside the promo
        self.assertEqual(self.card.monthly_interest, Decimal("0.00"))
        self.assertTrue(self.card.in_promo)

    def test_strategy_and_lump(self):
        r = self.client.get(reverse("projection"), {"extra": "100", "extra_from": date.today().replace(day=1), "strategy": "snowball", "lump": "500"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual([d.name for d in r.context["order"]], ["Collector", "Card"])
        self.assertEqual(r.context["order"][0].balance, Decimal("500"))  # lump taken off the first in order
        self.col.refresh_from_db(); self.assertEqual(self.col.balance, Decimal("1000"))  # not saved

    def test_settle_page_and_paid_closes(self):
        r = self.client.get(reverse("settle"))
        self.assertContains(r, "Collector")
        self.assertEqual(r.context["cards"][0]["tiers"][1]["amount"], Decimal("400"))
        r = self.client.post(reverse("settle"), {"debt": self.col.pk, "date": date.today(), "amount": "400", "status": "paid", "note": "ref 123"})
        self.assertRedirects(r, reverse("settle"))
        self.col.refresh_from_db()
        self.assertTrue(self.col.closed); self.assertEqual(self.col.balance, Decimal("0"))
        self.assertEqual(Payment.objects.get(debt=self.col).amount, Decimal("400"))
        self.assertEqual(SettlementOffer.objects.count(), 1)


class AccountTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("p", password="x" * 12, email="p@example.com")
        Debt.objects.create(owner=self.user, name="A", balance=Decimal("10"), monthly=Decimal("1"))

    def test_reset_flow_reachable_logged_out(self):
        from django.core import mail
        self.assertEqual(self.client.get(reverse("password_reset")).status_code, 200)
        self.assertEqual(self.client.get(reverse("privacy")).status_code, 200)
        r = self.client.post(reverse("password_reset"), {"email": "p@example.com"})
        self.assertRedirects(r, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/reset/", mail.outbox[0].body)

    def test_export_and_delete(self):
        self.client.force_login(self.user)
        r = self.client.get(reverse("account_export"))
        self.assertEqual(r["Content-Type"], "application/zip")
        import io, zipfile
        names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
        self.assertIn("debts.csv", names)
        r = self.client.post(reverse("account_delete"), {"confirm": "wrong"})
        self.assertEqual(get_user_model().objects.filter(username="p").count(), 1)
        r = self.client.post(reverse("account_delete"), {"confirm": "p"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(get_user_model().objects.filter(username="p").count(), 0)
        self.assertEqual(Debt.objects.count(), 0)

    def test_email_update(self):
        self.client.force_login(self.user)
        self.client.post(reverse("account_email"), {"email": "new@example.com"})
        self.user.refresh_from_db(); self.assertEqual(self.user.email, "new@example.com")


class OnboardingTests(TestCase):
    def test_new_user_sees_start_here_until_done(self):
        u = get_user_model().objects.create_user("n", password="x" * 12)
        self.client.force_login(u)
        r = self.client.get(reverse("overview"))
        self.assertContains(r, "Start here")
        self.assertEqual(sum(1 for s in r.context["start"] if s["done"]), 0)
        d = Debt.objects.create(owner=u, name="A", balance=Decimal("100"), monthly=Decimal("10"))
        BudgetLine.objects.create(owner=u, item="Pay", group="income", amount=Decimal("1000"))
        BudgetLine.objects.create(owner=u, item="Rent", group="home", amount=Decimal("-500"))
        r = self.client.get(reverse("overview"))
        self.assertEqual(sum(1 for s in r.context["start"] if s["done"]), 2)
        self.client.post(reverse("quick_pay", args=[d.pk]))
        r = self.client.get(reverse("overview"))
        self.assertIsNone(r.context["start"])
        self.assertNotContains(r, "Start here")

    def test_auth_pages_have_no_header(self):
        r = self.client.get(reverse("login"))
        self.assertNotContains(r, 'class="brand"')
        self.assertContains(r, "Everything you owe")


class OpenSignupTests(TestCase):
    def test_lockout_after_failures(self):
        get_user_model().objects.create_user("p", password="x" * 12)
        for _ in range(6):
            self.client.post(reverse("login"), {"username": "p", "password": "wrong-wrong"})
        self.assertIsNotNone(LoginAttempt.objects.get(key="p").locked_until)
        r = self.client.post(reverse("login"), {"username": "p", "password": "x" * 12})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Too many tries")
        LoginAttempt.objects.all().delete()
        r = self.client.post(reverse("login"), {"username": "p", "password": "x" * 12})
        self.assertEqual(r.status_code, 302)

    def test_signup_needs_consent_and_records_it(self):
        from django.test import override_settings
        with override_settings(ALLOW_SIGNUP=True):
            self.assertEqual(self.client.get(reverse("terms")).status_code, 200)
            r = self.client.post(reverse("signup"), {"username": "new", "email": "", "password1": "a-long-passw0rd", "password2": "a-long-passw0rd"})
            self.assertEqual(r.status_code, 200)
            self.assertFalse(get_user_model().objects.filter(username="new").exists())
            r = self.client.post(reverse("signup"), {"username": "new", "email": "", "password1": "a-long-passw0rd", "password2": "a-long-passw0rd", "agree": "on", "website": "spam"})
            self.assertFalse(get_user_model().objects.filter(username="new").exists())
            r = self.client.post(reverse("signup"), {"username": "new", "email": "", "password1": "a-long-passw0rd", "password2": "a-long-passw0rd", "agree": "on"})
            self.assertRedirects(r, reverse("overview"))
            self.assertEqual(Consent.objects.get(owner__username="new").terms_version, "2026-11-01")

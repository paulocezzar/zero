from decimal import Decimal

from django.conf import settings
import secrets

from django.db import models


class Debt(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="debts")
    KINDS = [
        ("card", "Credit card"),
        ("collector", "Collector"),
        ("family", "Family"),
        ("short", "Short-term"),
        ("loan", "Loan"),
    ]
    name = models.CharField(max_length=80)
    kind = models.CharField(max_length=12, choices=KINDS, default="collector")
    balance = models.DecimalField(max_digits=10, decimal_places=2)
    starting_balance = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="What it was when you started paying it down; for the progress rail")
    monthly = models.DecimalField(max_digits=9, decimal_places=2, default=0)
    apr = models.DecimalField("APR %", max_digits=5, decimal_places=2, default=0)
    promo_until = models.DateField("0% until", null=True, blank=True, help_text="For a balance-transfer deal: no interest before this date, the APR above after it")
    pay_day = models.PositiveSmallIntegerField(default=1)
    priority = models.PositiveSmallIntegerField(default=99)
    note = models.CharField(max_length=200, blank=True)
    closed = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["priority", "name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.starting_balance is None:
            self.starting_balance = self.balance
        super().save(*args, **kwargs)

    @property
    def progress(self):
        """0–100: share of the starting balance already paid."""
        if not self.starting_balance or self.starting_balance <= 0:
            return 0
        return max(0, min(100, int(100 - self.balance / self.starting_balance * 100)))

    @property
    def months_left(self):
        """Months to clear at the current payment, interest included. None if it never clears."""
        if self.balance <= 0:
            return 0
        if self.monthly <= 0:
            return None
        if not self.apr:
            return int(-(-self.balance // self.monthly))
        from .projection import simulate
        from datetime import date
        s = simulate([self], start=date.today().replace(day=1), planned=False).debts[0]
        if s.clear is None:
            return None
        d = date.today().replace(day=1)
        return (s.clear.year - d.year) * 12 + s.clear.month - d.month

    @property
    def never_clears(self):
        return self.balance > 0 and self.monthly > 0 and self.months_left is None

    @property
    def in_promo(self):
        from datetime import date
        return bool(self.promo_until and self.promo_until > date.today())

    @property
    def monthly_interest(self):
        if self.apr and self.balance > 0 and not self.in_promo:
            return (self.balance * self.apr / Decimal(100) / 12).quantize(Decimal("0.01"))
        return Decimal("0.00")


class Payment(models.Model):
    debt = models.ForeignKey(Debt, on_delete=models.CASCADE, related_name="payments")
    date = models.DateField()
    amount = models.DecimalField(max_digits=9, decimal_places=2)
    note = models.CharField(max_length=120, blank=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created"]

    def __str__(self):
        return f"{self.date} {self.debt} £{self.amount}"


CATEGORIES = [
    ("groceries", "Groceries"), ("amazon", "Amazon & shopping"), ("car", "Car & fuel"), ("eating", "Eating out"),
    ("home", "Home & bills"), ("tech", "Phones & tech"), ("subs", "Subscriptions"), ("family", "Family"),
    ("savings", "Savings"), ("cash", "Cash"), ("health", "Health"), ("kids", "Kids"), ("fun", "Fun & days out"), ("other", "Other"),
]
CATEGORY_LABELS = dict(CATEGORIES)


class BudgetLine(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="budget_lines")
    GROUPS = [
        ("income", "Income"), ("home", "Home"), ("family", "Family"), ("tech", "Phones & tech"),
        ("subs", "Subscriptions"), ("savings", "Savings"), ("everyday", "Everyday"), ("other", "Other"),
    ]
    item = models.CharField(max_length=80)
    group = models.CharField(max_length=10, choices=GROUPS, default="other")
    amount = models.DecimalField("£ per month (income positive, costs negative)", max_digits=9, decimal_places=2)
    pay_day = models.PositiveSmallIntegerField("Day of month", null=True, blank=True, help_text="When it leaves (1–28); blank for spread-out spending like groceries")
    category = models.CharField(max_length=12, choices=CATEGORIES, default="other", help_text="Spending is compared against the budget by category")
    note = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["group", "-amount"]

    def __str__(self):
        return self.item


class MonthCheckin(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="checkins")
    month = models.DateField(help_text="First of the month")
    income = models.DecimalField(max_digits=9, decimal_places=2)
    extra_income = models.DecimalField(max_digits=9, decimal_places=2, default=0)
    everyday = models.DecimalField("Everyday spend actual", max_digits=9, decimal_places=2, default=0)
    starling_on_3rd = models.DecimalField(max_digits=9, decimal_places=2, null=True, blank=True)
    aqua_balance = models.DecimalField(max_digits=9, decimal_places=2, null=True, blank=True)
    left_over = models.DecimalField(max_digits=9, decimal_places=2, default=0)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-month"]
        constraints = [models.UniqueConstraint(fields=["owner", "month"], name="one_checkin_per_month")]

    def __str__(self):
        return self.month.strftime("%b %Y")


class Outgoing(models.Model):
    """One thing that left: a card line, a cash spend, a one-off."""
    SOURCES = [("manual", "Logged by hand"), ("starling", "Starling import"), ("aqua", "Aqua import"), ("csv", "CSV import")]
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="outgoings")
    date = models.DateField()
    amount = models.DecimalField(max_digits=9, decimal_places=2)
    category = models.CharField(max_length=12, choices=CATEGORIES, default="other")
    merchant = models.CharField(max_length=80, blank=True)
    note = models.CharField(max_length=120, blank=True)
    source = models.CharField(max_length=10, choices=SOURCES, default="manual")
    import_key = models.CharField(max_length=64, blank=True, db_index=True, help_text="Hash of the statement line, so a re-import skips it")
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created"]
        constraints = [models.UniqueConstraint(fields=["owner", "import_key"], condition=models.Q(import_key__gt=""), name="one_import_per_line")]

    def __str__(self):
        return f"{self.date} {self.merchant or self.note} £{self.amount}"


class Snapshot(models.Model):
    """Where things stood on a day: total owed and the projected debt-free month. One per day per user."""
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="snapshots")
    day = models.DateField()
    total = models.DecimalField(max_digits=10, decimal_places=2)
    clear_month = models.DateField(null=True, blank=True)
    progress = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["day"]
        constraints = [models.UniqueConstraint(fields=["owner", "day"], name="one_snapshot_per_day")]


def _token():
    return secrets.token_urlsafe(24)


class CalendarToken(models.Model):
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="calendar_token")
    token = models.CharField(max_length=48, unique=True, default=_token)

    def reset(self):
        self.token = _token()
        self.save(update_fields=["token"])


class SettlementOffer(models.Model):
    """A full-and-final settlement offer made to a collector, and what came back."""
    STATUS = [("planned", "Planned"), ("offered", "Offered"), ("accepted", "Accepted"), ("rejected", "Rejected"), ("paid", "Paid & closed")]
    debt = models.ForeignKey(Debt, on_delete=models.CASCADE, related_name="offers")
    date = models.DateField()
    amount = models.DecimalField(max_digits=9, decimal_places=2)
    status = models.CharField(max_length=10, choices=STATUS, default="planned")
    note = models.CharField(max_length=200, blank=True, help_text="Who you spoke to, reference, what they said")

    class Meta:
        ordering = ["-date", "-id"]

    @property
    def pct(self):
        return int(self.amount / self.debt.balance * 100) if self.debt.balance > 0 else 0

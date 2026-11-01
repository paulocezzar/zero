from decimal import Decimal

from django.db import models


class Debt(models.Model):
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
        if self.balance <= 0:
            return 0
        if self.monthly <= 0:
            return None
        return int(-(-self.balance // self.monthly))

    @property
    def monthly_interest(self):
        if self.apr and self.balance > 0:
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


class BudgetLine(models.Model):
    GROUPS = [
        ("income", "Income"), ("home", "Home"), ("family", "Family"), ("tech", "Phones & tech"),
        ("subs", "Subscriptions"), ("savings", "Savings"), ("everyday", "Everyday"), ("other", "Other"),
    ]
    item = models.CharField(max_length=80)
    group = models.CharField(max_length=10, choices=GROUPS, default="other")
    amount = models.DecimalField("£ per month (income positive, costs negative)", max_digits=9, decimal_places=2)
    note = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["group", "-amount"]

    def __str__(self):
        return self.item


class MonthCheckin(models.Model):
    month = models.DateField(unique=True, help_text="First of the month")
    income = models.DecimalField(max_digits=9, decimal_places=2)
    extra_income = models.DecimalField(max_digits=9, decimal_places=2, default=0)
    everyday = models.DecimalField("Everyday spend actual", max_digits=9, decimal_places=2, default=0)
    starling_on_3rd = models.DecimalField(max_digits=9, decimal_places=2, null=True, blank=True)
    aqua_balance = models.DecimalField(max_digits=9, decimal_places=2, null=True, blank=True)
    left_over = models.DecimalField(max_digits=9, decimal_places=2, default=0)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-month"]

    def __str__(self):
        return self.month.strftime("%b %Y")

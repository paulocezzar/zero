"""Month-by-month simulation of the debts.

Each month every open debt gets its monthly payment, interest is added where
there is an APR, and any extra goes to the debt highest in priority order
(plus the monthly of each debt already cleared, which rolls forward).
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

MAX_MONTHS = 180


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


@dataclass
class Sim:
    debt_id: int
    name: str
    start: Decimal
    bal: Decimal
    monthly: Decimal
    apr: Decimal
    promo_until: date | None = None
    clear: date | None = None
    interest: Decimal = Decimal("0")


@dataclass
class Result:
    debts: list[Sim]
    series: list[tuple[date, Decimal]] = field(default_factory=list)

    @property
    def all_clear(self):
        return all(d.bal <= 0 for d in self.debts)

    @property
    def last_month(self):
        return self.series[-1][0] if self.series else None


def simulate(debts, *, start: date, extra: Decimal = Decimal("0"), extra_from: date | None = None, planned: bool = True) -> Result:
    sims = [Sim(d.id, d.name, d.balance, d.balance, d.monthly, d.apr, getattr(d, "promo_until", None), clear=start if d.balance <= 0 else None) for d in debts]
    res = Result(sims, [(start, sum(s.bal for s in sims))])
    m = start
    for _ in range(MAX_MONTHS):
        m = add_months(m, 1)
        pot = Decimal("0")
        if planned and extra_from and m >= extra_from:
            pot += extra
        for s in sims:
            if s.bal <= 0:
                if planned and s.start > 0:
                    pot += s.monthly
                continue
            if s.apr > 0 and not (s.promo_until and m < s.promo_until):
                i = s.bal * s.apr / Decimal(100) / 12
                s.bal += i
                s.interest += i
            pay = min(s.monthly, s.bal)
            s.bal -= pay
            if s.bal <= Decimal("0.005"):
                s.bal = Decimal("0")
                s.clear = m
                if planned:
                    pot += s.monthly - pay
        if planned:
            for s in sims:
                if pot <= 0:
                    break
                if s.bal <= 0:
                    continue
                pay = min(pot, s.bal)
                s.bal -= pay
                pot -= pay
                if s.bal <= Decimal("0.005"):
                    s.bal = Decimal("0")
                    s.clear = m
        res.series.append((m, sum(s.bal for s in sims)))
        if res.all_clear:
            break
    return res


def order(debts, strategy):
    """'mine' keeps the user's priority; 'avalanche' highest APR first (promo deals count as 0% until they end); 'snowball' smallest balance first."""
    debts = list(debts)
    if strategy == "avalanche":
        debts.sort(key=lambda d: (-(Decimal("0") if getattr(d, "in_promo", False) else d.apr), d.balance))
    elif strategy == "snowball":
        debts.sort(key=lambda d: (d.balance, d.priority))
    return debts

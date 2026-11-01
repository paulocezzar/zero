from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.db import transaction
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import projection
from .forms import BudgetLineForm, DebtForm, MonthForm, PaymentForm, ProjectionForm
from .models import BudgetLine, Debt, MonthCheckin, Payment

ZERO = Decimal("0")


def _first_of_month(d=None):
    d = d or date.today()
    return d.replace(day=1)


def budget_totals():
    lines = BudgetLine.objects.all()
    income = sum((l.amount for l in lines if l.amount > 0), ZERO)
    fixed = sum((l.amount for l in lines if l.amount < 0 and l.group != "everyday"), ZERO)
    everyday = sum((l.amount for l in lines if l.amount < 0 and l.group == "everyday"), ZERO)
    debt_pay = Debt.objects.filter(closed=False, balance__gt=0).aggregate(s=Sum("monthly"))["s"] or ZERO
    return {"income": income, "fixed": fixed, "everyday": everyday, "debt_pay": debt_pay, "left": income + fixed + everyday - debt_pay}


def open_debts():
    return Debt.objects.filter(closed=False)


# ---------- overview ----------

def overview(request):
    debts = list(open_debts())
    t = budget_totals()
    today = date.today()
    paid_ids = set(Payment.objects.filter(date__gte=_first_of_month(), debt_id__in=[d.id for d in debts]).values_list("debt_id", flat=True))
    due, done = [], []
    for d in debts:
        if d.balance <= 0 or d.monthly <= 0:
            continue
        if d.id in paid_ids:
            done.append(d)
            continue
        diff = d.pay_day - today.day
        if diff < 0:
            diff += 30
        if diff <= 14:
            due.append((diff, d))
    due.sort(key=lambda x: x[0])
    bills = []
    for b in BudgetLine.objects.filter(amount__lt=0, pay_day__isnull=False):
        diff = b.pay_day - today.day
        if diff < 0:
            diff += 30
        if diff <= 14:
            bills.append((diff, b))
    bills.sort(key=lambda x: x[0])
    interest_debts = [d for d in debts if d.apr > 0 and d.balance > 0]
    plan = projection.simulate(debts, start=_first_of_month(), extra=Decimal("250"), extra_from=projection.add_months(_first_of_month(), 4))
    plan_clear = {s.debt_id: s.clear for s in plan.debts}
    last = MonthCheckin.objects.first()
    start_total = sum(((d.starting_balance or d.balance) for d in debts), ZERO)
    total = sum((d.balance for d in debts), ZERO)
    progress = int(100 - total / start_total * 100) if start_total > 0 else 0
    ctx = {
        "progress": max(0, min(100, progress)),
        "plan_total_clear": plan.last_month if plan.all_clear else None,
        "total": sum((d.balance for d in debts), ZERO),
        "interest_total": sum((d.balance for d in interest_debts), ZERO),
        "interest_monthly": sum((d.monthly_interest for d in interest_debts), ZERO),
        "t": t, "due": due, "done": done, "bills": bills, "debts": debts, "plan_clear": plan_clear, "last": last,
        "recent": Payment.objects.select_related("debt")[:8],
    }
    return render(request, "tracker/overview.html", ctx)


# ---------- debts ----------

def debt_list(request):
    return render(request, "tracker/debts.html", {"debts": Debt.objects.all()})


def debt_edit(request, pk=None):
    debt = get_object_or_404(Debt, pk=pk) if pk else None
    form = DebtForm(request.POST or None, instance=debt)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Debt saved.")
        return redirect("debts")
    return render(request, "tracker/form.html", {"form": form, "title": debt.name if debt else "Add a debt", "back": "debts", "delete": debt})


@require_POST
def debt_delete(request, pk):
    get_object_or_404(Debt, pk=pk).delete()
    messages.success(request, "Debt removed.")
    return redirect("debts")


@require_POST
def debt_move(request, pk, direction):
    debts = list(Debt.objects.all())
    for i, d in enumerate(debts):
        d.priority = i
    idx = next(i for i, d in enumerate(debts) if d.pk == pk)
    j = idx - 1 if direction == "up" else idx + 1
    if 0 <= j < len(debts):
        debts[idx].priority, debts[j].priority = j, idx
    Debt.objects.bulk_update(debts, ["priority"])
    return redirect("debts")


# ---------- payments ----------

def payment_list(request):
    initial = {"date": date.today()}
    if request.GET.get("debt"):
        try:
            d = Debt.objects.get(pk=request.GET["debt"])
            initial.update(debt=d, amount=d.monthly)
        except (Debt.DoesNotExist, ValueError):
            pass
    form = PaymentForm(request.POST or None, initial=initial)
    form.fields["debt"].queryset = open_debts()
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            p = form.save()
            Debt.objects.filter(pk=p.debt_id).update(balance=max(ZERO, p.debt.balance - p.amount))
        messages.success(request, f"Logged £{p.amount} to {p.debt.name}.")
        return redirect("payments")
    return render(request, "tracker/payments.html", {"form": form, "payments": Payment.objects.select_related("debt")[:300]})


@require_POST
def payment_undo(request, pk):
    p = get_object_or_404(Payment, pk=pk)
    with transaction.atomic():
        Debt.objects.filter(pk=p.debt_id).update(balance=p.debt.balance + p.amount)
        p.delete()
    messages.success(request, "Payment undone and balance restored.")
    return redirect("payments")


# ---------- month ----------

def month_list(request):
    pk = request.GET.get("edit")
    inst = MonthCheckin.objects.filter(pk=pk).first() if pk else None
    t = budget_totals()
    form = MonthForm(request.POST or None, instance=inst, initial={"month": _first_of_month(), "income": t["income"]})
    if request.method == "POST" and form.is_valid():
        m = form.save(commit=False)
        m.month = m.month.replace(day=1)
        m.left_over = m.income + m.extra_income + t["fixed"] - t["debt_pay"] - m.everyday
        existing = MonthCheckin.objects.filter(month=m.month).exclude(pk=m.pk).first()
        if existing:
            m.pk = existing.pk
        m.save()
        messages.success(request, f"Saved {m}.")
        return redirect("month")
    return render(request, "tracker/month.html", {"form": form, "months": MonthCheckin.objects.all(), "t": t})


# ---------- budget ----------

def budget_list(request):
    pk = request.GET.get("edit")
    inst = BudgetLine.objects.filter(pk=pk).first() if pk else None
    form = BudgetLineForm(request.POST or None, instance=inst)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Budget line saved.")
        return redirect("budget")
    lines = BudgetLine.objects.all()
    groups = []
    for key, label in BudgetLine.GROUPS:
        g = [l for l in lines if l.group == key]
        if g:
            groups.append((label, g, sum((l.amount for l in g), ZERO)))
    return render(request, "tracker/budget.html", {"form": form, "groups": groups, "t": budget_totals(), "editing": inst})


@require_POST
def budget_delete(request, pk):
    get_object_or_404(BudgetLine, pk=pk).delete()
    return redirect("budget")


# ---------- projection ----------

def projection_view(request):
    start = _first_of_month()
    form = ProjectionForm(request.GET or None, initial={"extra": 250, "extra_from": projection.add_months(start, 4)})
    extra, extra_from = Decimal("250"), projection.add_months(start, 4)
    if form.is_valid():
        extra, extra_from = form.cleaned_data["extra"], form.cleaned_data["extra_from"]
    debts = list(open_debts())
    base = projection.simulate(debts, start=start, planned=False)
    plan = projection.simulate(debts, start=start, extra=extra, extra_from=extra_from)
    rows = []
    for s in plan.debts:
        b = next(x for x in base.debts if x.debt_id == s.debt_id)
        if s.start > 0:
            rows.append({"name": s.name, "balance": s.start, "base_clear": b.clear, "plan_clear": s.clear, "interest": s.interest})
    horizon = min(len(base.series), len(plan.series) + 12)
    chart = {
        "labels": [m.strftime("%b %Y") for m, _ in base.series[:horizon]],
        "base": [float(v) for _, v in base.series[:horizon]],
        "plan": ([float(v) for _, v in plan.series] + [0.0] * horizon)[:horizon],
    }
    return render(request, "tracker/projection.html", {"form": form, "rows": rows, "base": base, "plan": plan, "chart": chart})


# ---------- PWA ----------

def manifest(request):
    from django.templatetags.static import static
    return JsonResponse({
        "id": "/", "name": "Zero", "short_name": "Zero", "description": "Debts, payments and the month, in one place.",
        "start_url": "/", "scope": "/", "display": "standalone", "orientation": "portrait",
        "background_color": "#f7f6f2", "theme_color": "#1f6f6a",
        "icons": [
            {"src": static("tracker/icon-192.png"), "sizes": "192x192", "type": "image/png"},
            {"src": static("tracker/icon-512.png"), "sizes": "512x512", "type": "image/png"},
            {"src": static("tracker/icon-192-maskable.png"), "sizes": "192x192", "type": "image/png", "purpose": "maskable"},
            {"src": static("tracker/icon-512-maskable.png"), "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    })


@require_POST
def quick_pay(request, pk):
    """One tap from the overview: log this debt's monthly payment dated today."""
    d = get_object_or_404(Debt, pk=pk, closed=False)
    if Payment.objects.filter(debt=d, date__gte=_first_of_month()).exists():
        messages.info(request, f"{d.name} is already logged this month. Use Pay for an extra payment.")
        return redirect("overview")
    if d.monthly > 0:
        with transaction.atomic():
            Payment.objects.create(debt=d, date=date.today(), amount=d.monthly, note="quick")
            Debt.objects.filter(pk=d.pk).update(balance=max(ZERO, d.balance - d.monthly))
        messages.success(request, f"Logged £{d.monthly} to {d.name}.")
    return redirect("overview")


def profile(request):
    return render(request, "tracker/profile.html")

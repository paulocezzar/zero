from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_not_required
from django.db import transaction
from django.db.models import Sum
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import projection, spending
from .forms import BudgetLineForm, DebtForm, ImportForm, MonthForm, OfferForm, OutgoingForm, PaymentForm, ProjectionForm, SignupForm
from .models import CATEGORIES, CATEGORY_LABELS, BudgetLine, CalendarToken, Debt, MonthCheckin, Outgoing, Payment, SettlementOffer, Snapshot

ZERO = Decimal("0")


def _first_of_month(d=None):
    d = d or date.today()
    return d.replace(day=1)


def budget_totals(user):
    lines = BudgetLine.objects.filter(owner=user)
    income = sum((l.amount for l in lines if l.amount > 0), ZERO)
    fixed = sum((l.amount for l in lines if l.amount < 0 and l.group != "everyday"), ZERO)
    everyday = sum((l.amount for l in lines if l.amount < 0 and l.group == "everyday"), ZERO)
    debt_pay = Debt.objects.filter(owner=user, closed=False, balance__gt=0).aggregate(s=Sum("monthly"))["s"] or ZERO
    return {"income": income, "fixed": fixed, "everyday": everyday, "debt_pay": debt_pay, "left": income + fixed + everyday - debt_pay}


def open_debts(user):
    return Debt.objects.filter(owner=user, closed=False)


def _month_range(first):
    nxt = projection.add_months(first, 1)
    return first, nxt


def spent_this_month(user, first=None):
    first, nxt = _month_range(first or _first_of_month())
    return Outgoing.objects.filter(owner=user, date__gte=first, date__lt=nxt).aggregate(s=Sum("amount"))["s"] or ZERO


def category_rails(user, first):
    """Per category: budgeted (positive), spent, share, state. A category whose whole budget
    is lines with a pay day (rent, Sky, phones) is 'fixed': it leaves by direct debit and is
    shown separately from everyday spending."""
    first, nxt = _month_range(first)
    budget, loose = {}, {}
    for b in BudgetLine.objects.filter(owner=user, amount__lt=0):
        budget[b.category] = budget.get(b.category, ZERO) - b.amount
        if b.pay_day is None:
            loose[b.category] = loose.get(b.category, ZERO) - b.amount
    spent = {}
    for o in Outgoing.objects.filter(owner=user, date__gte=first, date__lt=nxt).values("category").annotate(s=Sum("amount")):
        spent[o["category"]] = o["s"]
    rails = []
    for key, label in CATEGORIES:
        b, sp = budget.get(key, ZERO), spent.get(key, ZERO)
        if b == 0 and sp == 0:
            continue
        pct = int(sp / b * 100) if b > 0 else (100 if sp > 0 else 0)
        rails.append({"key": key, "label": label, "budget": b, "spent": sp, "left": b - sp, "pct": min(pct, 100), "over": b > 0 and sp > b,
                      "nobudget": b == 0, "fixed": key != "other" and b > 0 and loose.get(key, ZERO) == 0})
    rails.sort(key=lambda r: (r["fixed"], -r["spent"], -r["budget"]))
    return rails


PLAN_EXTRA = Decimal("250")
PLAN_FROM_MONTHS = 4


def plan_for(debts, start=None):
    start = start or _first_of_month()
    return projection.simulate(debts, start=start, extra=PLAN_EXTRA, extra_from=projection.add_months(start, PLAN_FROM_MONTHS))


def record_snapshot(user):
    """Called whenever balances change: keeps a per-day history of total owed and the projected clear month."""
    debts = list(open_debts(user))
    total = sum((d.balance for d in debts), ZERO)
    start_total = sum(((d.starting_balance or d.balance) for d in debts), ZERO)
    progress = int(100 - total / start_total * 100) if start_total > 0 else 0
    plan = plan_for(debts)
    Snapshot.objects.update_or_create(owner=user, day=date.today(), defaults={"total": total, "clear_month": plan.last_month if plan.all_clear else None, "progress": max(0, min(100, progress))})


def _log_quick(d):
    """Log a debt's usual monthly payment dated today. Returns False if already logged this month."""
    if Payment.objects.filter(debt=d, date__gte=_first_of_month()).exists() or d.monthly <= 0:
        return False
    with transaction.atomic():
        Payment.objects.create(debt=d, date=date.today(), amount=d.monthly, note="quick")
        Debt.objects.filter(pk=d.pk).update(balance=max(ZERO, d.balance - d.monthly))
    return True


def paid_streak(user, debts):
    """Months in a row (counting back from last month, plus this month if complete) where every open debt got a payment."""
    active = [d for d in debts if d.monthly > 0 and d.balance > 0]
    if not active:
        return 0
    first_payment = Payment.objects.filter(debt__owner=user).order_by("date").values_list("date", flat=True).first()
    if not first_payment:
        return 0
    streak, m = 0, _first_of_month()
    this_month_done = all(Payment.objects.filter(debt=d, date__gte=m).exists() for d in active)
    if this_month_done:
        streak += 1
    m = projection.add_months(m, -1)
    while m >= first_payment.replace(day=1):
        nxt = projection.add_months(m, 1)
        if all(Payment.objects.filter(debt=d, date__gte=m, date__lt=nxt).exists() for d in active):
            streak += 1
            m = projection.add_months(m, -1)
        else:
            break
    return streak


# ---------- overview ----------

def overview(request):
    debts = list(open_debts(request.user))
    t = budget_totals(request.user)
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
    for b in BudgetLine.objects.filter(owner=request.user, amount__lt=0, pay_day__isnull=False):
        diff = b.pay_day - today.day
        if diff < 0:
            diff += 30
        if diff <= 14:
            bills.append((diff, b))
    bills.sort(key=lambda x: x[0])
    interest_debts = [d for d in debts if d.apr > 0 and d.balance > 0 and not d.in_promo]
    first = _first_of_month()
    plan = plan_for(debts)
    asis = projection.simulate(debts, start=first, planned=False)
    plan_clear = {s.debt_id: s.clear for s in plan.debts}
    asis_clear = {s.debt_id: s.clear for s in asis.debts}
    last = MonthCheckin.objects.filter(owner=request.user).first()
    start_total = sum(((d.starting_balance or d.balance) for d in debts), ZERO)
    total = sum((d.balance for d in debts), ZERO)
    progress = int(100 - total / start_total * 100) if start_total > 0 else 0
    # group what's due by day so one tap can log the lot
    groups = []
    for diff, d in due:
        if groups and groups[-1]["diff"] == diff:
            groups[-1]["debts"].append(d)
        else:
            groups.append({"diff": diff, "date": today + timedelta(days=diff), "debts": [d]})
    for g in groups:
        g["total"] = sum((d.monthly for d in g["debts"]), ZERO)
    # next win: the first debt to disappear with the plan
    upcoming = sorted(((c, d) for d in debts if d.balance > 0 and (c := plan_clear.get(d.id))), key=lambda x: x[0])
    next_win = None
    if upcoming:
        c, d = upcoming[0]
        next_win = {"debt": d, "month": c, "months": (c.year - first.year) * 12 + c.month - first.month}
    rails = [r for r in category_rails(request.user, first) if not r["fixed"]]
    spent = sum((r["spent"] for r in rails), ZERO)
    clear = plan.last_month if plan.all_clear else None
    ctx = {
        "progress": max(0, min(100, progress)),
        "plan_total_clear": clear, "clear_iso": clear.isoformat() if clear else "",
        "asis_total_clear": asis.last_month if asis.all_clear else None,
        "total": total,
        "interest_total": sum((d.balance for d in interest_debts), ZERO),
        "interest_monthly": sum((d.monthly_interest for d in interest_debts), ZERO),
        "no_apr": [d for d in debts if d.kind == "card" and d.apr == 0 and d.balance > 0],
        "t": t, "due": due, "groups": groups, "done": done, "bills": bills, "debts": debts, "plan_clear": plan_clear, "asis_clear": asis_clear, "last": last,
        "next_win": next_win, "streak": paid_streak(request.user, debts),
        "spent": spent, "everyday_budget": -t["everyday"], "days_left": (projection.add_months(first, 1) - today).days, "rails": rails[:5],
        "recent": Payment.objects.filter(debt__owner=request.user).select_related("debt")[:6],
    }
    return render(request, "tracker/overview.html", ctx)


# ---------- debts ----------

def debt_list(request):
    return render(request, "tracker/debts.html", {"debts": Debt.objects.filter(owner=request.user)})


def debt_edit(request, pk=None):
    debt = get_object_or_404(Debt, pk=pk, owner=request.user) if pk else None
    form = DebtForm(request.POST or None, instance=debt)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.owner = request.user
        obj.save()
        record_snapshot(request.user)
        messages.success(request, "Debt saved.")
        return redirect("debts")
    return render(request, "tracker/form.html", {"form": form, "title": debt.name if debt else "Add a debt", "back": "debts", "delete": debt})


@require_POST
def debt_delete(request, pk):
    get_object_or_404(Debt, pk=pk, owner=request.user).delete()
    messages.success(request, "Debt removed.")
    return redirect("debts")


@require_POST
def debt_move(request, pk, direction):
    debts = list(Debt.objects.filter(owner=request.user))
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
            d = Debt.objects.get(pk=request.GET["debt"], owner=request.user)
            initial.update(debt=d, amount=d.monthly)
        except (Debt.DoesNotExist, ValueError):
            pass
    form = PaymentForm(request.POST or None, initial=initial)
    form.fields["debt"].queryset = open_debts(request.user)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            p = form.save()
            Debt.objects.filter(pk=p.debt_id).update(balance=max(ZERO, p.debt.balance - p.amount))
        record_snapshot(request.user)
        messages.success(request, f"Logged £{p.amount} to {p.debt.name}.")
        return redirect("payments")
    return render(request, "tracker/payments.html", {"form": form, "payments": Payment.objects.filter(debt__owner=request.user).select_related("debt")[:300]})


@require_POST
def payment_undo(request, pk):
    _r = _payment_undo(request, pk)
    record_snapshot(request.user)
    return _r


def _payment_undo(request, pk):
    p = get_object_or_404(Payment, pk=pk, debt__owner=request.user)
    with transaction.atomic():
        Debt.objects.filter(pk=p.debt_id).update(balance=p.debt.balance + p.amount)
        p.delete()
    messages.success(request, "Payment undone and balance restored.")
    return redirect("payments")


# ---------- month ----------

def month_list(request):
    pk = request.GET.get("edit")
    inst = MonthCheckin.objects.filter(pk=pk, owner=request.user).first() if pk else None
    t = budget_totals(request.user)
    form = MonthForm(request.POST or None, instance=inst, initial={"month": _first_of_month(), "income": t["income"], "everyday": spent_this_month(request.user)})
    if request.method == "POST" and form.is_valid():
        m = form.save(commit=False)
        m.owner = request.user
        m.month = m.month.replace(day=1)
        if not m.everyday:
            m.everyday = spent_this_month(request.user, m.month)
        m.left_over = m.income + m.extra_income + t["fixed"] - t["debt_pay"] - m.everyday
        existing = MonthCheckin.objects.filter(owner=request.user, month=m.month).exclude(pk=m.pk).first()
        if existing:
            m.pk = existing.pk
        m.save()
        record_snapshot(request.user)
        messages.success(request, f"Saved {m}.")
        return redirect("month")
    return render(request, "tracker/month.html", {"form": form, "months": MonthCheckin.objects.filter(owner=request.user), "t": t})


# ---------- budget ----------

def budget_list(request):
    pk = request.GET.get("edit")
    inst = BudgetLine.objects.filter(pk=pk, owner=request.user).first() if pk else None
    form = BudgetLineForm(request.POST or None, instance=inst)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.owner = request.user
        obj.save()
        messages.success(request, "Budget line saved.")
        return redirect("budget")
    lines = BudgetLine.objects.filter(owner=request.user)
    groups = []
    for key, label in BudgetLine.GROUPS:
        g = [l for l in lines if l.group == key]
        if g:
            groups.append((label, g, sum((l.amount for l in g), ZERO)))
    return render(request, "tracker/budget.html", {"form": form, "groups": groups, "t": budget_totals(request.user), "editing": inst})


@require_POST
def budget_delete(request, pk):
    get_object_or_404(BudgetLine, pk=pk, owner=request.user).delete()
    return redirect("budget")


# ---------- projection ----------

def projection_view(request):
    start = _first_of_month()
    form = ProjectionForm(request.GET or None, initial={"extra": 250, "extra_from": projection.add_months(start, 4), "strategy": "mine", "lump": 0})
    extra, extra_from, strategy, lump = Decimal("250"), projection.add_months(start, 4), "mine", ZERO
    if form.is_valid():
        extra, extra_from = form.cleaned_data["extra"], form.cleaned_data["extra_from"]
        strategy = form.cleaned_data.get("strategy") or "mine"
        lump = form.cleaned_data.get("lump") or ZERO
    debts = list(open_debts(request.user))
    base = projection.simulate(debts, start=start, planned=False)
    ordered = projection.order(debts, strategy)
    if lump > 0:
        # a lump sum now goes down the order like extra money would
        pot = lump
        for d in ordered:
            take = min(pot, d.balance)
            d.balance -= take
            pot -= take
            if pot <= 0:
                break
    plan = projection.simulate(ordered, start=start, extra=extra, extra_from=extra_from)
    mine = projection.simulate(projection.order(debts, "mine"), start=start, extra=extra, extra_from=extra_from) if strategy != "mine" else plan
    rows = []
    for s_ in plan.debts:
        b = next(x for x in base.debts if x.debt_id == s_.debt_id)
        if b.start > 0:
            rows.append({"name": s_.name, "balance": b.start, "base_clear": b.clear, "plan_clear": s_.clear, "interest": s_.interest})
    horizon = min(len(base.series), len(plan.series) + 12)
    chart = {
        "labels": [m.strftime("%b %Y") for m, _ in base.series[:horizon]],
        "base": [float(v) for _, v in base.series[:horizon]],
        "plan": ([float(v) for _, v in plan.series] + [0.0] * horizon)[:horizon],
    }
    snaps = list(Snapshot.objects.filter(owner=request.user, clear_month__isnull=False))
    history = {"labels": [x.day.strftime("%-d %b %y") for x in snaps], "months": [((x.clear_month.year - x.day.year) * 12 + x.clear_month.month - x.day.month) for x in snaps], "clear": [x.clear_month.strftime("%b %Y") for x in snaps], "total": [float(x.total) for x in snaps]}
    total_interest = {"base": sum((x.interest for x in base.debts), ZERO), "plan": sum((x.interest for x in plan.debts), ZERO), "mine": sum((x.interest for x in mine.debts), ZERO)}
    return render(request, "tracker/projection.html", {"form": form, "rows": rows, "base": base, "plan": plan, "mine": mine, "strategy": strategy, "lump": lump, "chart": chart, "history": history, "history_n": len(snaps), "ti": total_interest, "order": ordered})


# ---------- settlements ----------

def settle(request):
    """Full-and-final settlement planner for collector accounts."""
    debts = [d for d in open_debts(request.user) if d.kind == "collector" and d.balance > 0]
    form = OfferForm(request.POST or None, initial={"date": date.today()})
    form.fields["debt"].queryset = Debt.objects.filter(owner=request.user, kind="collector", closed=False)
    if request.method == "POST" and form.is_valid():
        o = form.save()
        if o.status == "paid":
            with transaction.atomic():
                Payment.objects.create(debt=o.debt, date=o.date, amount=o.amount, note="settlement")
                Debt.objects.filter(pk=o.debt_id).update(balance=ZERO, closed=True)
            record_snapshot(request.user)
            messages.success(request, f"{o.debt.name} settled and closed. Keep the letter.")
        else:
            messages.success(request, "Offer recorded.")
        return redirect("settle")
    cards = []
    for d in debts:
        months = d.months_left
        tiers = []
        for pct in (30, 40, 50):
            amt = (d.balance * pct / 100).quantize(Decimal("1"))
            tiers.append({"pct": pct, "amount": amt, "saves": d.balance - amt})
        cards.append({"debt": d, "months": months, "years": round(months / 12, 1) if months else None, "tiers": tiers, "offers": list(d.offers.all()[:5])})
    total = sum((d.balance for d in debts), ZERO)
    return render(request, "tracker/settle.html", {"cards": cards, "form": form, "total": total, "at40": (total * 40 / 100).quantize(Decimal("1")), "saves40": total - (total * 40 / 100).quantize(Decimal("1"))})


@require_POST
def offer_delete(request, pk):
    get_object_or_404(SettlementOffer, pk=pk, debt__owner=request.user).delete()
    return redirect("settle")


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
    d = get_object_or_404(Debt, pk=pk, owner=request.user, closed=False)
    if _log_quick(d):
        record_snapshot(request.user)
        messages.success(request, f"Logged £{d.monthly} to {d.name}.")
    else:
        messages.info(request, f"{d.name} is already logged this month. Use Pay for an extra payment.")
    return redirect("overview")


@require_POST
def quick_pay_all(request):
    """Log the usual payment for every debt listed (one day's worth of direct debits)."""
    ids = [int(i) for i in request.POST.getlist("ids") if i.isdigit()]
    logged = [d.name for d in Debt.objects.filter(pk__in=ids, owner=request.user, closed=False) if _log_quick(d)]
    if logged:
        record_snapshot(request.user)
        messages.success(request, f"Logged {len(logged)}: {', '.join(logged)}.")
    else:
        messages.info(request, "Those are already logged this month.")
    return redirect("overview")


def profile(request):
    tok, _ = CalendarToken.objects.get_or_create(owner=request.user)
    if request.method == "POST" and request.POST.get("action") == "reset_calendar":
        tok.reset()
        messages.success(request, "Calendar link reset. Re-subscribe on your phone.")
        return redirect("profile")
    host = request.get_host()
    return render(request, "tracker/profile.html", {"cal_url": f"webcal://{host}/cal/{tok.token}.ics", "cal_https": request.build_absolute_uri(f"/cal/{tok.token}.ics"), "email_configured": settings.EMAIL_CONFIGURED})


@require_POST
def account_email(request):
    email = (request.POST.get("email") or "").strip()
    from django.core.validators import validate_email
    from django.core.exceptions import ValidationError
    try:
        if email:
            validate_email(email)
    except ValidationError:
        messages.error(request, "That doesn't look like an email address.")
        return redirect("profile")
    request.user.email = email
    request.user.save(update_fields=["email"])
    messages.success(request, "Email saved." if email else "Email removed.")
    return redirect("profile")


def account_export(request):
    """Everything this account holds, as a zip of CSVs."""
    import csv, io, zipfile
    u = request.user
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        def sheet(name, header, rows):
            f = io.StringIO(); w = csv.writer(f); w.writerow(header); w.writerows(rows); z.writestr(f"{name}.csv", f.getvalue())
        sheet("debts", ["name", "kind", "balance", "starting_balance", "monthly", "apr", "promo_until", "pay_day", "priority", "note", "closed"],
              [(d.name, d.kind, d.balance, d.starting_balance, d.monthly, d.apr, d.promo_until, d.pay_day, d.priority, d.note, d.closed) for d in Debt.objects.filter(owner=u)])
        sheet("payments", ["date", "debt", "amount", "note"], [(p.date, p.debt.name, p.amount, p.note) for p in Payment.objects.filter(debt__owner=u).select_related("debt")])
        sheet("budget", ["item", "group", "category", "amount", "pay_day", "note"], [(b.item, b.group, b.category, b.amount, b.pay_day, b.note) for b in BudgetLine.objects.filter(owner=u)])
        sheet("checkins", ["month", "income", "extra_income", "everyday", "starling_on_3rd", "aqua_balance", "left_over", "note"],
              [(m.month, m.income, m.extra_income, m.everyday, m.starling_on_3rd, m.aqua_balance, m.left_over, m.note) for m in MonthCheckin.objects.filter(owner=u)])
        sheet("spending", ["date", "amount", "category", "merchant", "note", "source"], [(o.date, o.amount, o.category, o.merchant, o.note, o.source) for o in Outgoing.objects.filter(owner=u)])
        sheet("offers", ["date", "debt", "amount", "status", "note"], [(o.date, o.debt.name, o.amount, o.status, o.note) for o in SettlementOffer.objects.filter(debt__owner=u).select_related("debt")])
        sheet("snapshots", ["day", "total", "clear_month", "progress"], [(x.day, x.total, x.clear_month, x.progress) for x in Snapshot.objects.filter(owner=u)])
    resp = HttpResponse(buf.getvalue(), content_type="application/zip")
    resp["Content-Disposition"] = f'attachment; filename="zero-{u.username}-{date.today():%Y-%m-%d}.zip"'
    return resp


@require_POST
def account_delete(request):
    """Deletes the account and everything attached to it (all models cascade from the user)."""
    if request.POST.get("confirm") != request.user.username:
        messages.error(request, "Type your username exactly to confirm.")
        return redirect("profile")
    from django.contrib.auth import logout
    u = request.user
    logout(request)
    u.delete()
    return render(request, "tracker/deleted.html")


@login_not_required
def privacy(request):
    return render(request, "tracker/privacy.html", {"email_configured": settings.EMAIL_CONFIGURED})


@login_not_required
def calendar_feed(request, token):
    """Subscribable calendar: every debt payment and bill for the next 12 months, with a reminder the day before."""
    tok = get_object_or_404(CalendarToken, token=token)
    user = tok.owner
    first = _first_of_month()
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Zero//Payments//EN", "CALSCALE:GREGORIAN", "X-WR-CALNAME:Zero — payments", "REFRESH-INTERVAL;VALUE=DURATION:P1D"]
    items = [(f"debt-{d.pk}", d.pay_day, d.name, d.monthly, "Debt payment") for d in open_debts(user) if d.monthly > 0 and d.balance > 0]
    items += [(f"bill-{b.pk}", b.pay_day, b.item, -b.amount, "Bill") for b in BudgetLine.objects.filter(owner=user, amount__lt=0, pay_day__isnull=False)]
    for i in range(12):
        m = projection.add_months(first, i)
        for key, day, name, amount, kind in items:
            d = m.replace(day=min(day, 28))
            if d < date.today():
                continue
            lines += ["BEGIN:VEVENT", f"UID:{key}-{d:%Y%m}@zero", f"DTSTAMP:{date.today():%Y%m%d}T000000Z", f"DTSTART;VALUE=DATE:{d:%Y%m%d}", f"DTEND;VALUE=DATE:{d + timedelta(days=1):%Y%m%d}",
                      f"SUMMARY:£{amount:.2f} {name}".replace(",", "\,"), f"DESCRIPTION:{kind} · logged in Zero", "BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:Tomorrow: £{amount:.2f} {name}", "TRIGGER:-P1D", "END:VALARM", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return HttpResponse("\r\n".join(lines) + "\r\n", content_type="text/calendar; charset=utf-8")


@login_not_required
def signup(request):
    if not settings.ALLOW_SIGNUP:
        raise Http404
    if request.user.is_authenticated:
        return redirect("overview")
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Welcome. Start by adding your first debt, then your income and bills on Budget.")
        return redirect("debts")
    return render(request, "tracker/signup.html", {"form": form})


# ---------- spending ----------

def _month_param(request):
    m = request.GET.get("m") or request.POST.get("m") or ""
    try:
        y, mo = m.split("-")
        return date(int(y), int(mo), 1)
    except (ValueError, AttributeError):
        return _first_of_month()


def spending_view(request):
    first = _month_param(request)
    first, nxt = _month_range(first)
    today = date.today()
    form = OutgoingForm(request.POST or None, initial={"date": today if first <= today < nxt else first})
    if request.method == "POST" and form.is_valid():
        o = form.save(commit=False)
        o.owner = request.user
        o.save()
        messages.success(request, f"Logged {o.merchant or CATEGORY_LABELS[o.category]} £{o.amount}.")
        return redirect(f"{request.path}?m={o.date:%Y-%m}")
    items = Outgoing.objects.filter(owner=request.user, date__gte=first, date__lt=nxt)
    rails = category_rails(request.user, first)
    everyday = [r for r in rails if not r["fixed"]]
    fixed = [r for r in rails if r["fixed"]]
    total = sum((r["spent"] for r in everyday), ZERO)
    budget = sum((r["budget"] for r in everyday), ZERO)
    days_left = max(0, (nxt - today).days) if first <= today < nxt else 0
    ctx = {"form": form, "items": items, "rails": everyday, "fixed": fixed, "fixed_total": sum((r["spent"] for r in fixed), ZERO), "total": total, "budget": budget, "left": budget - total, "days_left": days_left,
           "first": first, "prev": projection.add_months(first, -1), "next": nxt if nxt <= _first_of_month() else None, "is_current": first == _first_of_month(),
           "cats": CATEGORIES}
    return render(request, "tracker/spending.html", ctx)


@require_POST
def outgoing_delete(request, pk):
    o = get_object_or_404(Outgoing, pk=pk, owner=request.user)
    m = f"{o.date:%Y-%m}"
    o.delete()
    return redirect(f"/spending/?m={m}")


def import_view(request):
    """Step 1: upload. Step 2: review rows held in the session. Step 3: confirm."""
    if request.method == "POST" and request.POST.get("stage") == "confirm":
        pending = request.session.get("import_rows") or []
        source = request.session.get("import_source", "csv")
        created = skipped = 0
        existing = set(Outgoing.objects.filter(owner=request.user, import_key__in=[r["key"] for r in pending]).values_list("import_key", flat=True))
        for i, r in enumerate(pending):
            if request.POST.get(f"skip-{i}") or r["key"] in existing:
                skipped += 1
                continue
            cat = request.POST.get(f"cat-{i}", r["category"])
            if cat not in CATEGORY_LABELS:
                cat = "other"
            Outgoing.objects.create(owner=request.user, date=date.fromisoformat(r["date"]), amount=Decimal(r["amount"]), category=cat, merchant=r["desc"], note=r.get("ref", ""), source=source, import_key=r["key"])
            created += 1
        request.session.pop("import_rows", None)
        request.session.pop("import_source", None)
        messages.success(request, f"Imported {created} lines" + (f", skipped {skipped}." if skipped else "."))
        return redirect("spending")

    form = ImportForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        f = form.cleaned_data["statement"]
        if f.size > 2_000_000:
            form.add_error("statement", "That file is over 2 MB. Export a shorter date range.")
        else:
            source, rows = spending.parse(f.read(), request.user.id)
            if not rows:
                form.add_error("statement", "No spending lines found. Zero reads Starling and Aqua CSV exports, or any CSV with date, description and amount columns.")
            else:
                existing = set(Outgoing.objects.filter(owner=request.user, import_key__in=[r["key"] for r in rows]).values_list("import_key", flat=True))
                rows = [dict(r, date=r["date"].isoformat(), amount=str(r["amount"]), seen=r["key"] in existing) for r in rows][:400]
                request.session["import_rows"] = rows
                request.session["import_source"] = source
                return redirect("import_review")
    return render(request, "tracker/import.html", {"form": form})


def import_review(request):
    rows = request.session.get("import_rows")
    if not rows:
        return redirect("import")
    source = request.session.get("import_source", "csv")
    new = [r for r in rows if not r["seen"]]
    return render(request, "tracker/import_review.html", {"rows": rows, "source": source, "cats": CATEGORIES, "new_count": len(new), "seen_count": len(rows) - len(new),
                  "total": sum((Decimal(r["amount"]) for r in new if not r["skip"]), ZERO)})

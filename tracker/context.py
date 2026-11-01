NAV = [("overview", "Overview"), ("debts", "Debts"), ("payments", "Payments"), ("month", "This month"), ("budget", "Budget"), ("projection", "Projection")]
NAV_MOBILE = []


def nav(request):
    return {"nav": NAV, "nav_mobile": NAV_MOBILE}

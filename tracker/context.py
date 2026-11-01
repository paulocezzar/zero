NAV = [("overview", "Overview"), ("debts", "Debts"), ("payments", "Payments"), ("month", "This month"), ("budget", "Budget"), ("projection", "Projection")]
NAV_MOBILE = []


from django.conf import settings


def nav(request):
    return {"nav": NAV, "nav_mobile": NAV_MOBILE, "allow_signup": settings.ALLOW_SIGNUP}

from django.contrib import admin

from .models import BudgetLine, Debt, MonthCheckin, Payment

admin.site.register(Debt)
admin.site.register(Payment)
admin.site.register(BudgetLine)
admin.site.register(MonthCheckin)

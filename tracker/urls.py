from django.contrib.auth.decorators import login_not_required
from django.urls import path
from django.views.generic import TemplateView

from . import views

urlpatterns = [
    path("", views.overview, name="overview"),
    path("debts/", views.debt_list, name="debts"),
    path("debts/new/", views.debt_edit, name="debt_new"),
    path("debts/<int:pk>/", views.debt_edit, name="debt_edit"),
    path("debts/<int:pk>/delete/", views.debt_delete, name="debt_delete"),
    path("debts/<int:pk>/move/<str:direction>/", views.debt_move, name="debt_move"),
    path("payments/", views.payment_list, name="payments"),
    path("me/", views.profile, name="profile"),
    path("me/email/", views.account_email, name="account_email"),
    path("me/export/", views.account_export, name="account_export"),
    path("me/delete/", views.account_delete, name="account_delete"),
    path("privacy/", views.privacy, name="privacy"),
    path("terms/", views.terms, name="terms"),
    path("signup/", views.signup, name="signup"),
    path("pay/<int:pk>/", views.quick_pay, name="quick_pay"),
    path("pay/all/", views.quick_pay_all, name="quick_pay_all"),
    path("cal/<str:token>.ics", views.calendar_feed, name="calendar_feed"),
    path("payments/<int:pk>/undo/", views.payment_undo, name="payment_undo"),
    path("spending/", views.spending_view, name="spending"),
    path("spending/<int:pk>/delete/", views.outgoing_delete, name="outgoing_delete"),
    path("spending/<int:pk>/category/", views.outgoing_recat, name="outgoing_recat"),
    path("spending/import/", views.import_view, name="import"),
    path("spending/import/review/", views.import_review, name="import_review"),
    path("month/", views.month_list, name="month"),
    path("budget/", views.budget_list, name="budget"),
    path("budget/<int:pk>/delete/", views.budget_delete, name="budget_delete"),
    path("projection/", views.projection_view, name="projection"),
    path("settle/", views.settle, name="settle"),
    path("settle/<int:pk>/delete/", views.offer_delete, name="offer_delete"),
    path("manifest.json", login_not_required(views.manifest), name="manifest"),
    path("icon.svg", login_not_required(TemplateView.as_view(template_name="tracker/icon.svg", content_type="image/svg+xml")), name="icon"),
    path("sw.js", login_not_required(TemplateView.as_view(template_name="tracker/sw.js", content_type="application/javascript")), name="sw"),
]

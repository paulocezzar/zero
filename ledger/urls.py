from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_not_required
from django.urls import include, path

from tracker.forms import LockoutAuthenticationForm

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(template_name="tracker/login.html", authentication_form=LockoutAuthenticationForm), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("password/", auth_views.PasswordChangeView.as_view(template_name="tracker/password.html", success_url="/me/"), name="password_change"),
    path("reset/", login_not_required(auth_views.PasswordResetView.as_view(template_name="tracker/reset.html", email_template_name="tracker/reset_email.txt", subject_template_name="tracker/reset_subject.txt", success_url="/reset/sent/")), name="password_reset"),
    path("reset/sent/", login_not_required(auth_views.PasswordResetDoneView.as_view(template_name="tracker/reset_sent.html")), name="password_reset_done"),
    path("reset/<uidb64>/<token>/", login_not_required(auth_views.PasswordResetConfirmView.as_view(template_name="tracker/reset_confirm.html", success_url="/reset/done/")), name="password_reset_confirm"),
    path("reset/done/", login_not_required(auth_views.PasswordResetCompleteView.as_view(template_name="tracker/reset_done.html")), name="password_reset_complete"),
    path("", include("tracker.urls")),
]

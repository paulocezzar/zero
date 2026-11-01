from django import forms
from datetime import timedelta

from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import BudgetLine, Debt, MonthCheckin, Outgoing, Payment, SettlementOffer


class Bootstrap:
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        for f in self.fields.values():
            cls = "form-select" if isinstance(f.widget, forms.Select) else "form-control"
            f.widget.attrs.setdefault("class", cls)
            if isinstance(f.widget, forms.NumberInput):
                f.widget.attrs.setdefault("inputmode", "decimal")


class DebtForm(Bootstrap, forms.ModelForm):
    class Meta:
        model = Debt
        fields = ["name", "kind", "balance", "starting_balance", "monthly", "apr", "promo_until", "pay_day", "priority", "note", "closed"]
        widgets = {"closed": forms.CheckboxInput(attrs={"class": "form-check-input"}), "promo_until": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}


class PaymentForm(Bootstrap, forms.ModelForm):
    class Meta:
        model = Payment
        fields = ["date", "debt", "amount", "note"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}


class BudgetLineForm(Bootstrap, forms.ModelForm):
    class Meta:
        model = BudgetLine
        fields = ["item", "group", "category", "amount", "pay_day", "note"]


class MonthForm(Bootstrap, forms.ModelForm):
    class Meta:
        model = MonthCheckin
        fields = ["month", "income", "extra_income", "everyday", "starling_on_3rd", "aqua_balance", "note"]
        widgets = {"month": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.fields["everyday"].required = False
        self.fields["everyday"].help_text = "Leave blank to use what you logged on Spending"

    def clean_everyday(self):
        return self.cleaned_data.get("everyday") or 0


class ProjectionForm(Bootstrap, forms.Form):
    STRATEGIES = [("mine", "My order"), ("avalanche", "Highest interest first"), ("snowball", "Smallest balance first")]
    extra = forms.DecimalField(label="Extra £ per month", initial=250, min_value=0, max_value=5000)
    extra_from = forms.DateField(label="Extra starts from", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    strategy = forms.ChoiceField(choices=STRATEGIES, initial="mine", required=False)
    lump = forms.DecimalField(label="One-off lump sum now", initial=0, min_value=0, max_value=100000, required=False)


class SignupForm(Bootstrap, UserCreationForm):
    email = forms.EmailField(required=False, help_text="Optional — only used to reset your password")
    agree = forms.BooleanField(label="I've read the terms and the privacy notice", error_messages={"required": "You need to accept the terms to create an account."})
    website = forms.CharField(required=False, widget=forms.HiddenInput)  # honeypot: humans never fill this

    class Meta(UserCreationForm.Meta):
        fields = ("username", "email")

    def clean_website(self):
        if self.cleaned_data.get("website"):
            raise forms.ValidationError("Something went wrong. Try again.")
        return ""


class LockoutAuthenticationForm(AuthenticationForm):
    """Standard sign-in form with a per-username lockout after repeated failures."""

    def clean(self):
        from django.conf import settings as st
        from django.utils import timezone
        from .models import LoginAttempt
        key = (self.cleaned_data.get("username") or "").strip().lower()[:160]
        attempt = LoginAttempt.objects.filter(key=key).first() if key else None
        if attempt and attempt.locked_until and attempt.locked_until > timezone.now():
            mins = int((attempt.locked_until - timezone.now()).total_seconds() // 60) + 1
            raise forms.ValidationError(f"Too many tries. Locked for {mins} more minute{'s' if mins != 1 else ''}.", code="locked")
        try:
            data = super().clean()
        except forms.ValidationError:
            if key:
                attempt, _ = LoginAttempt.objects.get_or_create(key=key)
                attempt.failures += 1
                if attempt.failures >= st.LOGIN_MAX_FAILURES:
                    attempt.locked_until = timezone.now() + timedelta(minutes=st.LOGIN_LOCK_MINUTES)
                    attempt.failures = 0
                attempt.save()
            raise
        if attempt:
            attempt.delete()
        return data



class OutgoingForm(Bootstrap, forms.ModelForm):
    class Meta:
        model = Outgoing
        fields = ["date", "amount", "category", "merchant", "note"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"), "merchant": forms.TextInput(attrs={"placeholder": "Where"}), "note": forms.TextInput(attrs={"placeholder": "Optional"})}


class ImportForm(forms.Form):
    statement = forms.FileField(label="Statement CSV", widget=forms.ClearableFileInput(attrs={"class": "form-control", "accept": ".csv,text/csv"}))


class OfferForm(Bootstrap, forms.ModelForm):
    class Meta:
        model = SettlementOffer
        fields = ["debt", "date", "amount", "status", "note"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

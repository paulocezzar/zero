from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import BudgetLine, Debt, MonthCheckin, Payment


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
        fields = ["name", "kind", "balance", "starting_balance", "monthly", "apr", "pay_day", "priority", "note", "closed"]
        widgets = {"closed": forms.CheckboxInput(attrs={"class": "form-check-input"})}


class PaymentForm(Bootstrap, forms.ModelForm):
    class Meta:
        model = Payment
        fields = ["date", "debt", "amount", "note"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}


class BudgetLineForm(Bootstrap, forms.ModelForm):
    class Meta:
        model = BudgetLine
        fields = ["item", "group", "amount", "pay_day", "note"]


class MonthForm(Bootstrap, forms.ModelForm):
    class Meta:
        model = MonthCheckin
        fields = ["month", "income", "extra_income", "everyday", "starling_on_3rd", "aqua_balance", "note"]
        widgets = {"month": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}


class ProjectionForm(Bootstrap, forms.Form):
    extra = forms.DecimalField(label="Extra £ per month", initial=250, min_value=0)
    extra_from = forms.DateField(label="Extra starts from", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))


class SignupForm(Bootstrap, UserCreationForm):
    class Meta(UserCreationForm.Meta):
        fields = ("username",)

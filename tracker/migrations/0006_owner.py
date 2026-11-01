from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def assign_first_user(apps, schema_editor):
    User = apps.get_model(settings.AUTH_USER_MODEL)
    user = User.objects.order_by("id").first()
    if not user:
        return
    for name in ("Debt", "BudgetLine", "MonthCheckin"):
        apps.get_model("tracker", name).objects.filter(owner__isnull=True).update(owner=user)


class Migration(migrations.Migration):
    dependencies = [
        ("tracker", "0005_fill_budget_days"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.AddField(model_name="debt", name="owner", field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name="debts", to=settings.AUTH_USER_MODEL)),
        migrations.AddField(model_name="budgetline", name="owner", field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name="budget_lines", to=settings.AUTH_USER_MODEL)),
        migrations.AddField(model_name="monthcheckin", name="owner", field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name="checkins", to=settings.AUTH_USER_MODEL)),
        migrations.RunPython(assign_first_user, migrations.RunPython.noop),
        migrations.AlterField(model_name="debt", name="owner", field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="debts", to=settings.AUTH_USER_MODEL)),
        migrations.AlterField(model_name="budgetline", name="owner", field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="budget_lines", to=settings.AUTH_USER_MODEL)),
        migrations.AlterField(model_name="monthcheckin", name="owner", field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="checkins", to=settings.AUTH_USER_MODEL)),
        migrations.AlterField(model_name="monthcheckin", name="month", field=models.DateField(help_text="First of the month")),
        migrations.AddConstraint(model_name="monthcheckin", constraint=models.UniqueConstraint(fields=("owner", "month"), name="one_checkin_per_month")),
    ]

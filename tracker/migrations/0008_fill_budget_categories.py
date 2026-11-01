from django.db import migrations

GROUP_TO_CAT = {"home": "home", "family": "family", "tech": "tech", "subs": "subs", "savings": "savings", "other": "other", "income": "other"}
EVERYDAY = {"Groceries (estimate)": "groceries", "Amazon orders (estimate)": "amazon", "Car, fuel, travel (estimate)": "car", "Eating out / other (estimate)": "eating"}


def fill(apps, schema_editor):
    BudgetLine = apps.get_model("tracker", "BudgetLine")
    for b in BudgetLine.objects.all():
        b.category = EVERYDAY.get(b.item) or GROUP_TO_CAT.get(b.group, "other")
        b.save(update_fields=["category"])


class Migration(migrations.Migration):
    dependencies = [("tracker", "0007_outgoing")]
    operations = [migrations.RunPython(fill, migrations.RunPython.noop)]

from decimal import Decimal

from django.db import migrations

KNOWN = {
    "PRA Group (Barclaycard)": "13681.74", "Shop Direct (ACI)": "3016.92", "Vanda": "7656",
    "Link Financial": "2507.87", "Wescot (HSBC Visa)": "2988.57", "Aqua credit card": "6600",
    "V12 Retail Finance (ACI)": "1389.98", "Amazon instalments": "734.59",
}


def fill(apps, schema_editor):
    Debt = apps.get_model("tracker", "Debt")
    for d in Debt.objects.filter(starting_balance__isnull=True):
        d.starting_balance = Decimal(KNOWN.get(d.name, str(d.balance)))
        d.save(update_fields=["starting_balance"])


class Migration(migrations.Migration):
    dependencies = [("tracker", "0002_starting_balance")]
    operations = [migrations.RunPython(fill, migrations.RunPython.noop)]

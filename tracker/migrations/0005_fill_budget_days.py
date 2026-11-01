from django.db import migrations

DAYS = {"Take-home pay (The Newt)": 30, "Rent": 1, "Sky TV": 28, "Sky broadband": 11, "TV licence": 6, "Vanda \u2014 insurance element": 1,
        "Parents (Wise from Starling)": 1, "O2 \u00d72": 7, "Sky \u2014 MacBook Pro agreement": 13, "Sky \u2014 MacBook Air agreement": 14,
        "Netflix direct (cancel once linked to Sky)": 3, "Google Play, PlayStation, Apple": 10, "Software (Claude, ChatGPT, Google One, Proton)": 14,
        "Savings (Emergency \u00a350 + kids \u00a320)": 1, "Unite the Union": 7}


def fill(apps, schema_editor):
    BudgetLine = apps.get_model("tracker", "BudgetLine")
    for b in BudgetLine.objects.filter(pay_day__isnull=True):
        if b.item in DAYS:
            b.pay_day = DAYS[b.item]
            b.save(update_fields=["pay_day"])


class Migration(migrations.Migration):
    dependencies = [("tracker", "0004_budget_pay_day")]
    operations = [migrations.RunPython(fill, migrations.RunPython.noop)]

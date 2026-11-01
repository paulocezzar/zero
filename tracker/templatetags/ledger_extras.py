from django import template

register = template.Library()


@register.filter
def get_item(d, key):
    return d.get(key) if d else None


@register.filter
def gbp(value, places=0):
    """£1,234 or −£1,234; places=2 keeps pence."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "—"
    sign = "−" if v < 0 else ""
    fmt = "{:,.2f}" if int(places) == 2 else "{:,.0f}"
    return f"{sign}£{fmt.format(abs(v))}"

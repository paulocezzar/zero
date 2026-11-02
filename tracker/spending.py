"""Statement parsing and auto-categorisation for the Spending page."""
import csv
import hashlib
import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

# keyword → category. First match wins; checked against the upper-cased description.
RULES = [
    ("fuel", ["SHELL", "ESSO", "BP ", "TEXACO", "PETROL", "FUEL", "MFG ", "JET ", "GULF", "MORRISONS PETROL", "TESCO PFS", "SAINSBURYS PFS", "ASDA PETROL", "MURCO", "HARVEST ENERGY", "APPLEGREEN", "EG GROUP", "MOTO ", "WELCOME BREAK", "ROADCHEF", "CERTAS", "POWER NRG", "EV CHARG", "GRIDSERVE", "INSTAVOLT", "POD POINT", "OSPREY", "IONITY", "TESLA SUPERCHARGER"]),
    ("groceries", ["TESCO", "SAINSBURY", "ASDA", "LIDL", "ALDI", "MORRISON", "WAITROSE", "CO-OP", "COOP", "M&S", "MARKS", "ICELAND", "OCADO", "FARMFOODS", "SPAR", "NISA", "LONDIS", "BUDGENS", "PREMIER STORE", "ONE STOP", "COSTCO", "B&M", "HOME BARGAINS", "POUNDLAND"]),
    ("amazon", ["AMAZON", "AMZN", "IKEA", "MARKS & SPENCER", "M&S", "MARKS AND SPENCER", "EBAY", "ETSY", "ARGOS", "CURRYS", "JOHN LEWIS", "NEXT ", "PRIMARK", "H&M", "ZARA", "IKEA", "TEMU", "SHEIN", "VINTED", "AMAZON PRIME"]),
    ("car", ["NATIONAL TYRE", "AUTO ELECTRICAL", "GARAGE", "MOT CENTRE", "PARKING", "RINGGO", "JUSTPARK", "NCP", "DVLA", "HALFORDS", "KWIK FIT", "KWIK-FIT", "ATS EURO", "MOT ", "TRAINLINE", "GWR", "SOUTH WESTERN", "NATIONAL RAIL", "TFL", "UBER", "BOLT", "STAGECOACH", "FIRST BUS", "ARRIVA", "NATIONAL EXPRESS", "CAR WASH", "INSURANCE", "ADMIRAL", "HASTINGS", "CHURCHILL", "DIRECT LINE"]),
    ("eating", ["PARSONS BAKERY", "GAIL", "BAKERY", "MCDONALD", "KFC", "BURGER KING", "GREGGS", "SUBWAY", "COSTA", "STARBUCKS", "PRET", "CAFFE NERO", "NERO", "DOMINO", "PIZZA", "DELIVEROO", "JUST EAT", "JUST-EAT", "UBER EATS", "UBER *EATS", "NANDO", "WAGAMAMA", "PUB", "INN ", "TAVERN", "RESTAURANT", "CAFE", "COFFEE", "BAKERY", "KEBAB", "CHIPPY", "FISH BAR", "TAKEAWAY", "WETHERSPOON", "TOBY", "HARVESTER", "FIVE GUYS", "TACO BELL", "BEEFEATER"]),
    ("home", ["SKY", "BT ", "VIRGIN MEDIA", "TV LICEN", "COUNCIL TAX", "COUNCIL", "WATER", "OCTOPUS", "BRITISH GAS", "EDF", "EON", "E.ON", "OVO", "SCOTTISH POWER", "SHELL ENERGY", "RENT", "LANDLORD", "LETTINGS", "SCREWFIX", "B&Q", "WICKES", "TOOLSTATION", "DUNELM", "THE RANGE", "WILKO"]),
    ("tech", ["O2", "EE ", "VODAFONE", "THREE", "GIFFGAFF", "APPLE.COM/BILL", "APPLE STORE", "CURRYS", "GOOGLE STORE"]),
    ("subs", ["NETFLIX", "SPOTIFY", "DISNEY", "PRIME VIDEO", "NOW TV", "YOUTUBE", "GOOGLE PLAY", "GOOGLE ONE", "GOOGLE *", "PLAYSTATION", "XBOX", "NINTENDO", "APPLE.COM", "ICLOUD", "ANTHROPIC", "CLAUDE", "OPENAI", "CHATGPT", "PROTON", "MICROSOFT", "ADOBE", "DROPBOX", "AUDIBLE", "KINDLE", "PATREON", "TWITCH", "DAZN", "PARAMOUNT", "CRUNCHYROLL", "GYM", "PUREGYM", "THE GYM", "DAVID LLOYD", "UNITE THE UNION", "UNITE"]),
    ("family", ["WISE", "TRANSFERWISE", "REMITLY", "WESTERN UNION", "MONEYGRAM", "WORLDREMIT", "VANDA"]),
    ("savings", ["SAVINGS", "SPACE", "ISA", "MONZO POT", "CHIP", "PLUM", "MOONPIG"]),
    ("cash", ["CASH", "ATM", "CASHPOINT", "LINK ATM", "WITHDRAWAL", "POST OFFICE"]),
    ("health", ["BOOTS", "SUPERDRUG", "PHARMACY", "CHEMIST", "LLOYDS PHARM", "DENTIST", "DENTAL", "OPTICIAN", "SPECSAVERS", "VISION EXPRESS", "NHS", "HOLLAND & BARRETT", "HOLLAND AND BARRETT"]),
    ("kids", ["SMYTHS", "TOYS", "SCHOOL", "NURSERY", "CLUB", "PARENTPAY", "MOTHERCARE", "JOJO", "ENTERTAINER"]),
    ("fun", ["CINEMA", "ODEON", "VUE", "CINEWORLD", "BOWL", "ZOO", "MUSEUM", "TICKETMASTER", "SEE TICKETS", "EVENTBRITE", "NATIONAL TRUST", "MERLIN", "LEGOLAND", "ALTON TOWERS", "SOFT PLAY", "STEAM", "EPIC GAMES", "PLAY STATION STORE"]),
]

# descriptions that are not spending: income, moves between own accounts, debt payments
SKIP = ["INTEREST", "CASH ADVANCE FEE", "FOREIGN EXCHANGE", "ONMO", "THE NEWT", "SALARY", "PAYROLL", "WAGES", "THE NEWT", "HMRC", "DWP", "CHILD BENEFIT", "UNIVERSAL CREDIT", "REFUND", "CASHBACK", "INTEREST", "TRANSFER", "FROM STARLING", "TO STARLING", "AQUA", "NEWDAY", "PAYMENT RECEIVED", "PAYMENT - THANK YOU", "DIRECT DEBIT PAYMENT", "PRA GROUP", "LINK FINANCIAL", "WESCOT", "ACI UK", "ACI ", "INTRUM", "RESOLVECALL", "CAPQUEST", "MOORCROFT", "LOWELL", "CABOT", "STEPCHANGE", "BARCLAYCARD", "CAPITAL ONE", "VANQUIS", "KLARNA", "CLEARPAY", "MONZO", "REVOLUT", "PAYPAL TOP", "SAVINGS SPACE", "ROUND UP", "ROUND-UP"]


def categorise(desc):
    d = (desc or "").upper()
    for cat, words in RULES:
        if any(w in d for w in words):
            return cat
    return "other"


def is_skip(desc):
    d = (desc or "").upper()
    return any(w in d for w in SKIP)


def _dec(s):
    s = (s or "").replace("£", "").replace(",", "").strip()
    if not s:
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _date(s):
    s = (s or "").strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def _key(user_id, d, amount, desc):
    raw = f"{user_id}|{d}|{amount}|{(desc or '').strip().upper()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:40]


def parse(data, user_id):
    """Return (source, rows). Each row: dict(date, amount, desc, category, skip, key).
    Amount is positive = money out. Rows that are money in are dropped."""
    text = data.decode("utf-8-sig", errors="replace") if isinstance(data, bytes) else data
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return "csv", []
    header = [h.strip().lower() for h in rows[0]]
    body = rows[1:]

    def col(*names):
        for n in names:
            for i, h in enumerate(header):
                if h == n or h.startswith(n):
                    return i
        return None

    out = []
    if "counter party" in header or "counterparty" in header:
        source = "starling"
        i_date, i_who, i_ref, i_amt, i_type = col("date"), col("counter party", "counterparty"), col("reference"), col("amount"), col("type")
        for r in body:
            if len(r) <= max(i for i in (i_date, i_who, i_amt) if i is not None):
                continue
            amt = _dec(r[i_amt])
            if amt is None or amt >= 0:
                continue
            desc = (r[i_who] or "").strip()
            ref = (r[i_ref] or "").strip() if i_ref is not None else ""
            ttype = (r[i_type] or "").strip() if i_type is not None else ""
            full = f"{desc} {ref} {ttype}"
            out.append(_row(user_id, _date(r[i_date]), -amt, desc, ref, full))
    else:
        # NewDay (Aqua, Marbles, Fluid…) exports: Date, Description, Note, Amount(GBP) — spending positive, payments negative
        is_card = any("transaction" in h or "card" in h for h in header) or ("note" in header and any(h.startswith("amount") for h in header))
        i_date = col("date", "transaction date", "posting date")
        i_desc = col("description", "merchant", "details", "narrative", "name")
        i_note = col("note", "memo")
        i_amt = col("amount", "value")
        i_debit, i_credit = col("debit", "money out", "paid out"), col("credit", "money in", "paid in")
        if not is_card and i_amt is not None:
            # no debit/credit split and no card headers: decide the sign convention from the data itself.
            # A card statement has mostly positive lines plus a few negative "payment received"; a bank export is the reverse.
            vals = [_dec(r[i_amt]) for r in body if len(r) > i_amt]
            vals = [v for v in vals if v is not None]
            pays = [r for r in body if len(r) > i_desc and "PAYMENT RECEIVED" in (r[i_desc] or "").upper()]
            if vals and (sum(1 for v in vals if v > 0) > len(vals) * 0.7) and (pays or i_credit is None):
                is_card = True
        source = "aqua" if is_card else "csv"
        for r in body:
            if i_date is None or i_desc is None or len(r) <= max(i_date, i_desc):
                continue
            desc = (r[i_desc] or "").strip()
            note = (r[i_note] or "").strip() if i_note is not None and len(r) > i_note else ""
            amt = None
            if i_debit is not None and len(r) > i_debit and _dec(r[i_debit]):
                amt = _dec(r[i_debit])
            elif i_amt is not None and len(r) > i_amt:
                a = _dec(r[i_amt])
                if a is None:
                    continue
                # Card statements usually list spending as positive and payments as negative/credit.
                if i_credit is not None and len(r) > i_credit and _dec(r[i_credit]):
                    continue
                if source == "aqua":
                    amt = a if a > 0 else None
                else:
                    amt = -a if a < 0 else None
            if amt is None or amt <= 0:
                continue
            out.append(_row(user_id, _date(r[i_date]), amt, desc, note, f"{desc} {note}"))
    out = [r for r in out if r["date"]]
    out.sort(key=lambda r: r["date"], reverse=True)
    return source, out


def _row(user_id, d, amount, desc, ref, full):
    skip = is_skip(full)
    merchant = re.sub(r"\s+", " ", desc)[:80]
    return {"date": d, "amount": amount.quantize(Decimal("0.01")), "desc": merchant, "ref": ref[:120], "category": "other" if skip else categorise(full), "skip": skip, "key": _key(user_id, d, amount, full)}

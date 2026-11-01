# Zero

A small private Django app: debts, payments, monthly check-in, budget, and a month-by-month payoff projection. Installable on a phone as a web app.

## Run locally

    python -m venv .venv && . .venv/bin/activate
    pip install -r requirements.txt
    python manage.py migrate
    python manage.py createsuperuser
    python manage.py seed
    DJANGO_DEBUG=1 python manage.py runserver

## Deploy on Render

Build: `./build.sh` · Start: `gunicorn ledger.wsgi:application`

Environment variables: `DJANGO_SECRET_KEY`, `DATABASE_URL` (from the Render Postgres), `ADMIN_USERNAME` and `ADMIN_PASSWORD` (used once, on first build, to create the sign-in user). `RENDER_EXTERNAL_HOSTNAME` is set by Render and added to ALLOWED_HOSTS automatically.

Security: every page requires sign-in; HTTPS-only cookies, HSTS, CSRF, clickjacking and MIME protections are on when DEBUG is off. Change the initial password from the Password link after first sign-in.

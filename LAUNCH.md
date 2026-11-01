# Opening Zero to other people

Everything in the app is ready for strangers: consent at sign-up, lockout after six wrong passwords, honeypot on the sign-up form, export and delete on Profile, Privacy and Terms pages. What's left is outside the code.

## Render

1. **Paid Postgres** (Render → New → PostgreSQL, Basic, ~$7/mo). The free one expires 1 December and free databases are wiped. Create it, copy the *Internal Database URL* into the web service's `DATABASE_URL`, redeploy. The build runs migrations; the seed only loads for the very first user, never again.
2. **Email** so password resets send. Free SMTP from Brevo (300/day) or Resend (3,000/mo). Then in the web service's environment:
   - `EMAIL_URL` = `smtp://USERNAME:PASSWORD@smtp-relay.brevo.com:587` (URL-encode any `@` or `:` in the password)
   - `EMAIL_FROM` = `Zero <you@yourdomain>`
3. **Open sign-up**: `ALLOW_SIGNUP=1`. Remove it to go invite-only again.
4. Optional, if the cold-start wait bothers people: upgrade the web service to Starter (~$7/mo).

## Domain

Buy one (Cloudflare or Porkbun, a few pounds a year), add it under the service's *Custom Domains*, point the DNS where Render says. Then add it to `ALLOWED_HOSTS` in the environment (comma-separated) — the Render hostname is picked up automatically, a custom one isn't.

## ICO

With other people's financial data you're a data controller. Register at ico.org.uk/registration before the first stranger signs up; the lowest tier is £52 a year (£47 by direct debit). Keep the certificate with the Render account details.

## Terms version

`TERMS_VERSION` in `ledger/settings.py`. Bump it when the terms change materially; each account records which version it accepted (`Consent`), so you can see who hasn't seen the new one.

## Before announcing

- Sign up as a stranger in a private window; do the three Start-here steps; export; delete.
- Request a password reset and check the email arrives.
- Try six wrong passwords and see the lock message.

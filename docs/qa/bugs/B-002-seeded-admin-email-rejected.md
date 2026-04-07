# Bug B-002: Seeded admin email `admin@phoenix.local` is rejected by /auth/login with 422

Severity: P3 (dev-only friction; not a Polymarket bug)
Env: API http://localhost:8011, pydantic EmailStr, 2026-04-07

Steps:
1. Run `scripts/seed_user.py` — creates `admin@phoenix.local` / `phoenix123`.
2. `curl -X POST http://localhost:8011/auth/login -H 'Content-Type: application/json' -d '{"email":"admin@phoenix.local","password":"phoenix123"}'`

Expected:
200 with a JWT (this is the documented dev login in `docs/OPENCLAW_SETUP_GUIDE.md` and `scripts/seed_user.py`).

Actual:
```
HTTP 422
{"detail":[{"type":"value_error","loc":["body","email"],
"msg":"value is not a valid email address: The part after the @-sign is a special-use or reserved name that cannot be used with email.",
"ctx":{"reason":"The part after the @-sign is a special-use or reserved name that cannot be used with email."}}]}
```

Pydantic's `EmailStr` (via `email-validator`) rejects `.local` as a reserved/special-use TLD. The seed script happily creates the row, but login can never succeed for that address. This leaves the documented dev bootstrap path broken.

Expected vs Actual:
- Expected: either (a) the seed script default email uses a non-reserved TLD like `admin@phoenix.dev`, or (b) the login schema is relaxed in dev, or (c) docs are updated.
- Actual: mismatch between seed script defaults and login validator → login always 422.

Suspected area:
- `scripts/seed_user.py` (line 26 default `admin@phoenix.local`)
- `apps/api/src/routes/auth.py` login request schema using `EmailStr`
- `docs/OPENCLAW_SETUP_GUIDE.md` (4 references to `admin@phoenix.local`)

Workaround used for this smoke:
- `POST /auth/register` with `quill@phoenix.dev` / `phoenix123` — worked immediately, logged in.

Suggested fix (for Devin via Build):
- Change `DEFAULT_EMAIL` in `scripts/seed_user.py` to `admin@phoenix.dev` and update docs references. Or, gate the validator to allow reserved TLDs when `ENV=local`.

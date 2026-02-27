# E2E Regression: Authentication & User Management

## Prerequisites
- Application running locally (http://localhost:3080)
- Clean database or test user credentials

---

## TC-AUTH-001: User Registration
**Steps:**
1. Navigate to http://localhost:3080/register
2. Enter name: "Test User", email: "test@example.com", password: "Password123!"
3. Click "Create Account"

**Expected:**
- Success message appears
- Email verification prompt shown
- User record created in `users` table with `email_verified=false`

---

## TC-AUTH-002: Login with Unverified Email
**Steps:**
1. Navigate to http://localhost:3080/login
2. Enter email: "test@example.com", password: "Password123!"
3. Click "Sign In"

**Expected:**
- Error message: email not verified (or verification prompt)
- User NOT logged in

---

## TC-AUTH-003: Login with Valid Credentials
**Steps:**
1. Verify user email in database (set `email_verified=true`)
2. Navigate to http://localhost:3080/login
3. Enter valid email and password
4. Click "Sign In"

**Expected:**
- Redirected to Dashboard
- User name shown in sidebar
- JWT token stored in localStorage

---

## TC-AUTH-004: MFA Setup
**Steps:**
1. Log in as verified user
2. Navigate to System > MFA Setup (or /mfa-setup)
3. Scan QR code with authenticator app
4. Enter 6-digit TOTP code
5. Click "Enable MFA"

**Expected:**
- MFA enabled confirmation
- Next login requires TOTP code

---

## TC-AUTH-005: MFA Login
**Steps:**
1. Log out
2. Log in with email and password
3. Enter 6-digit TOTP code when prompted
4. Click "Verify"

**Expected:**
- Login succeeds
- Redirected to Dashboard

---

## TC-AUTH-006: Token Refresh
**Steps:**
1. Log in and wait for token to near expiry
2. Make any API call

**Expected:**
- Token refreshed automatically (401 → retry with new token)
- No user interruption

---

## TC-AUTH-007: Logout
**Steps:**
1. Click user avatar/name in sidebar
2. Click "Logout"

**Expected:**
- Redirected to /login
- localStorage cleared
- Protected routes inaccessible

---

## TC-AUTH-008: Access Management (Admin)
**Steps:**
1. Log in as admin user
2. Navigate to Access Management
3. Change a user's role from "trader" to "viewer"
4. Toggle a user's active status to disabled

**Expected:**
- Role change reflected immediately
- Disabled user cannot log in

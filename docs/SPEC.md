# SPEC.md — Niscala backend

> **Audience:** coding agents working in this repository.
> **Scope:** the FastAPI backend only. The Flutter Android app lives in a separate repository (`andinaufal120/niscala-app`) and renders what this API returns.
> **Status:** self-contained. Everything an agent needs to know about required backend behaviour is in this file. Do not look for requirements elsewhere.

Traceability IDs (`FR-xx`, `NFR-xx`, `UC-xx`, `TBD-x`, `U-x`) are stable keys shared with the project's requirements baseline (v1.1, 16-10-2026), the app repository and Jira. Use them in commit messages and PR descriptions, never in source code or test names.

Blocks between `<!-- shared:begin -->` and `<!-- shared:end -->` are identical in the app repository's `docs/SPEC.md`. Change them in both repositories together (see `CLAUDE.md`, "Shared sections").

---

## 1. Product

*Shared with niscala-app.*

<!-- shared:begin -->
Niscala ("Kelola Kost Tanpa Ribet") helps boarding-house (kos) owners and managers handle properties, rooms, tenants, rent payments and maintenance complaints in one Android app.

- Rent is paid **outside** the app (cash or bank transfer). The app records, verifies and tracks payment status. It never moves rent money.
- Two AI features set the product apart. Both are available only when the property owner has an active paid subscription (plan Basic or Pro):
    1. classification of maintenance complaints (category, urgency, suggested action);
    2. a natural-language summary of each tenant's payment pattern.
- Owners choose a plan: Gratis (1 property, 15 rooms, no AI), Basic (3 properties, unlimited rooms, AI) or Pro (unlimited properties, everything in Basic). Subscriptions are bought and renewed through Google Play Billing in the app; the backend verifies the purchase with Google.
- An AI failure never blocks saving data.
- Out of scope for v1.0: in-app rent payment, OAuth providers other than Google, iOS and web apps.
<!-- shared:end -->

## 2. Boundary of this repository

| The backend does (this repo)                                        | The app does (not this repo)                            |
|---------------------------------------------------------------------|---------------------------------------------------------|
| Store data, enforce permissions                                     | Render screens, forms, lists and states                 |
| Re-validate everything; it is the authority                         | Validate input before sending (format, required fields) |
| Compute billing dates, due dates, payment-pattern facts, risk flags | Show results the API returns                            |
| Decide subscription gating (FR-25, NFR-15) and report it            | Show subscription-gated content as the API reports it   |
| Call Gemini, retries, fallback (FR-28)                              | Show AI results or their pending/unavailable state      |
| Generate bills (FR-31), invitations, notifications                  | Pick files, share links, display QR codes               |

**Invariant:** every business rule is enforced here. The app never computes a rule-derived value locally, so if a screen needs one, the API must return it. A missing value is a contract gap: raise it in Plan mode.

## 3. Glossary

*Shared with niscala-app.*

<!-- shared:begin -->
Markdown docs use the format *Original term (English term)*. Code uses the English **code name** only.

| Term                                                | Code name                 | Meaning                                                                            |
|-----------------------------------------------------|---------------------------|------------------------------------------------------------------------------------|
| Niscala                                             | —                         | This product.                                                                      |
| Properti (Property)                                 | `Property`                | One kos location with rooms, owned by one Owner.                                   |
| Kamar (Room)                                        | `Room`                    | A rentable unit in a property. Occupancy is Terisi or Kosong.                      |
| Masa sewa (Lease)                                   | `Lease`                   | A tenant's occupancy of a room: start date, end date, rent, billing cycle, grace period. |
| Penyewa (Tenant)                                    | `Tenant`                  | User who occupies a room; joins through an invitation link.                        |
| Pemilik Kost (Owner)                                | `Owner`                   | User who owns one or more properties and holds the subscription.                   |
| Pengelola Kost (Manager)                            | `Manager`                 | Optional user assigned by an Owner to specific properties.                         |
| Admin (Admin)                                       | `Admin`                   | Internal user who manages all user accounts.                                       |
| Akun pengguna (User account)                        | `UserAccount`             | Any user's login identity: name, email, role and status. Admins manage all of them. |
| Manajemen kost (Management)                         | `management` (role group) | Owner and Manager together.                                                        |
| Rekening bank (Bank account)                        | `BankAccount`             | Optional per-property account for rent transfers: bank name, account number, account holder name. |
| Tarif dasar (Base rate)                             | `baseRate`                | A room's monthly price. Only pre-fills the rent of a new monthly lease.            |
| Tarif sewa (Rent)                                   | `rent`                    | The amount of one bill of a lease, per billing cycle. A change applies from the next bill onward. |
| Ukuran kamar (Room dimensions)                      | `lengthM`, `widthM`       | Optional, in metres. Area is length × width, for display only, never stored.       |
| Fasilitas (Facilities)                              | `facilities`              | Free-form tags on a room, normalized on save.                                      |
| Undangan (Invitation)                               | `Invitation`              | Lets a Tenant or Manager activate an account.                                      |
| Laporan keluhan (Complaint)                         | `Complaint`               | Free-text maintenance report from a Tenant.                                        |
| Klasifikasi AI (AI classification)                  | `ComplaintClassification` | Category, urgency and suggested action for a complaint, set by AI or by management (UC-36). |
| Catatan penanganan (Handling note)                  | `handlingNote`            | Optional note on a complaint status change. Visible to the Tenant.                 |
| Tagihan sewa (Rent bill)                            | `RentBill`                | Rent owed for one billing period. Generated by the backend (FR-31).                |
| Pembayaran (Payment)                                | `Payment`                 | The payment record attached to a rent bill.                                        |
| Siklus penagihan (Billing cycle)                    | `BillingCycle`            | Weekly, monthly, 3, 6 or 12 months. Default: monthly from the lease start date.    |
| Masa tenggang (Grace period)                        | `gracePeriodDays`         | Days after the bill date before a payment is late. Default: 0.                     |
| Jatuh tempo (Due date)                              | `dueDate`                 | Bill date + grace period. Computed by the backend.                                 |
| Ringkasan pola pembayaran (Payment-pattern summary) | `PaymentPatternSummary`   | AI-written sentence built from rule-computed payment facts.                        |
| Langganan (Subscription)                            | `Subscription`            | The Owner's paid plan that unlocks AI features and raises the property limit.     |
| Paket (Subscription plan)                           | `SubscriptionPlan`        | Gratis (`free`), Basic (`basic`) or Pro (`pro`): property and room limits, AI availability and prices. |
| Pesanan langganan (Subscription order)              | `SubscriptionOrder`       | One attempt to buy a paid plan through Google Play; tracks the purchase until it succeeds, fails or expires. |
| Sesi (Session)                                      | `Session`                 | One logged-in device of a user.                                                    |
| Notifikasi (Notification)                           | `Notification`            | In-app message about an event: bill, payment, complaint or account. Kept even when its push is off. |
| Pengaturan notifikasi (Notification settings)       | `NotificationSettings`    | Per-user push on/off switch per notification category.                             |
| Soft delete (Soft delete)                           | —                         | Marked inactive; history is kept.                                                  |
<!-- shared:end -->

The code names above are used in PEP 8 form in this repository (see `CLAUDE.md`, "Vocabulary"). Their wire form is set in §9.

## 4. Roles and permissions

*Shared with niscala-app.*

<!-- shared:begin -->
`✓` allowed · `A` only on properties assigned to the Manager · `—` not allowed

| Capability                                                   | Tenant | Owner | Manager | Admin |
|--------------------------------------------------------------|:------:|:-----:|:-------:|:-----:|
| View own room, lease, payments, complaints                   |   ✓   |   —   |    —    |   —   |
| Submit complaint, upload transfer receipt                    |   ✓   |   —   |    —    |   —   |
| Add / edit / delete property                                 |   —    |  ✓   |    —    |   —   |
| View property                                                |   —    |  ✓   |    A    |   —   |
| Add / view / edit / delete room                              |   —    |  ✓   |    A    |   —   |
| Add / view / edit / delete tenant                            |   —    |  ✓   |    A    |   —   |
| Verify/reject receipts, record cash, change payment status   |   —    |  ✓   |    A    |   —   |
| Occupancy dashboard, complaint list, change complaint status, classify complaint manually |   —    |  ✓   |    A    |   —   |
| Payment status of all tenants, payment-pattern view          |   —    |  ✓   |    A    |   —   |
| Add / view / edit / delete managers                          |   —    |  ✓   |    —    |   —   |
| Choose and pay for a subscription                            |   —    |  ✓   |    —    |   —   |
| View / edit / delete any user account                        |   —    |   —   |    —    |  ✓   |
| View / end own sessions, change own password                 |   ✓   |  ✓   |    ✓    |  ✓   |
| View own notifications, change own notification settings     |   ✓   |  ✓   |    ✓    |   —   |

Each role sees only the menus it is allowed to use. The backend enforces permissions; the app hides what a role cannot do.
<!-- shared:end -->

The API checks every request against this table. `A` means the check includes the Manager's current property assignments, so a removed assignment (UC-29) or a deleted Manager (UC-30) loses access immediately. Notifications are filtered the same way for a Manager: only assigned properties.

Checks run in this order: a missing or invalid session answers `ACCESS_TOKEN_INVALID` (401); an unverified email answers `EMAIL_NOT_VERIFIED` (403); a role the endpoint does not allow answers `FORBIDDEN` (403). A property the caller may not access answers `PROPERTY_NOT_FOUND` (404), the same as a property that does not exist or was deleted, so a response never reveals that someone else's property exists. Properties are soft-deleted (they keep a deletion time) and soft-deleted properties are never accessible.

## 5. Status vocabularies

*Shared with niscala-app.*

<!-- shared:begin -->
| Entity                           | Statuses — Indonesian label (English, `codeName`)                                                                                                                                                                     |
|----------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Room occupancy                   | Terisi (Occupied, `occupied`) · Kosong (Vacant, `vacant`)                                                                                                                                                             |
| Payment                          | Belum Bayar (Unpaid, `unpaid`) · Menunggu Verifikasi (Awaiting verification, `awaitingVerification`) · Lunas (Paid, `paid`) · Ditolak (Rejected, `rejected`)                                                          |
| Payment method                   | Transfer (Bank transfer, `transfer`) · Tunai (Cash, `cash`)                                                                                                                                                           |
| Login method                     | Google (Google, `google`) · Kata sandi (Password, `password`)                                                                                                                                                         |
| Billing cycle                    | Mingguan (Weekly, `weekly`) · Bulanan (Monthly, `monthly`) · 3 Bulan (Quarterly, `quarterly`) · 6 Bulan (Semiannual, `semiannual`) · 12 Bulan (Annual, `annual`) |
| Complaint                        | Baru (New, `new_`) · Diproses (In progress, `inProgress`) · Selesai (Done, `done`) |
| Complaint classification         | Menunggu Klasifikasi (Awaiting classification, `awaitingClassification`) · Belum Diklasifikasi (Not classified, `notClassified`) |
| Complaint urgency                | Rendah (Low, `low`) · Sedang (Medium, `medium`) · Tinggi (High, `high`) |
| Tenant account                   | Belum Diaktifkan (Not activated, `notActivated`) · Aktif (Active, `active`)                                                                                                                                           |
| Manager account                  | Belum Diaktifkan (Not activated, `notActivated`) · Aktif (Active, `active`)                                                                                                                                           |
| User account (Admin view)        | Aktif (Active, `active`) · Nonaktif (Suspended, `inactive`) · Dihapus (Deleted, `deleted`)                                                                                                                            |
| Subscription order / transaction | Menunggu Pembayaran (Awaiting payment, `awaitingPayment`) · Berhasil (Succeeded, `succeeded`) · Gagal (Failed, `failed`) · Kedaluwarsa (Expired, `expired`)                                                           |
| Subscription                     | Gratis (Free, `free`) · Aktif (Active, `active`) |
| Subscription plan                | Gratis (Free, `free`) · Basic (Basic, `basic`) · Pro (Pro, `pro`) |
| Subscription billing period      | Bulanan (Monthly, `monthly`) · Tahunan (Yearly, `yearly`) |

Complaint status moves forward one step at a time: *Baru* → *Diproses* → *Selesai*. Nothing changes after *Selesai*.

Classification state is separate from status. *Menunggu Klasifikasi* = AI was attempted and failed or timed out. *Belum Diklasifikasi* = the Owner had no active subscription when the complaint was saved, so AI was skipped. A classified complaint has neither.

Order status maps to Google Play like this: the order starts as *Menunggu Pembayaran*; a verified purchase in state purchased makes it *Berhasil*; a purchase Google reports as pending (for example pay at a convenience store) keeps it *Menunggu Pembayaran*; a purchase Google reports as failed or canceled makes it *Gagal*; an order whose purchase never completes within its time limit becomes *Kedaluwarsa*. Subscription *Gratis* means no paid period is running; *Aktif* means a paid period is running.

A *Nonaktif* account is suspended: it cannot log in and can be reactivated. A *Dihapus* account is soft-deleted, hidden from the default account list, and can never be reactivated. *Dihapus* is shown, never set, through the edit endpoint.

`new_` is only the Dart identifier, because `new` is reserved in Dart. The wire value is `"new"`.
<!-- shared:end -->

The allowed transitions are listed with the use case that causes them in §8.

## 6. Cross-cutting API rules

These apply to every use case below. Use cases do not repeat them.

1. **Session:** every endpoint except `GET /health` and the endpoints marked *public* in §9 requires a valid session, sent as an access token (§7). A missing, expired, revoked or invalid access token gets an authentication error with the code `ACCESS_TOKEN_INVALID`, which the app can tell apart from other errors and answers by refreshing the token.
2. **Errors** carry a stable error code, the field it belongs to (for validation errors), and an English message for developers and logs. The app shows Indonesian text mapped from the code, so validation errors can be shown next to their field. Every error response is one JSON object `{"code": string, "field": string or null, "message": string}`. `field` is the camelCase path of the offending request field (`bankAccount.accountNumber`, `facilities.0`) and is null when the error is not about one field. A request with several invalid fields reports the first one. A request that fails validation answers `422` with code `VALIDATION_FAILED`; any error not raised by a use case takes its HTTP status phrase as code (`NOT_FOUND`, `METHOD_NOT_ALLOWED`, `NOT_IMPLEMENTED`); an unexpected failure answers `500` with `INTERNAL_ERROR`. Use-case codes are listed with their use case. The codes are part of the OpenAPI document (declaring them there: U-9).
3. **Conflict:** a write based on data another user has changed since it was read is rejected with a conflict error and not applied (detection: U-15).
4. **Failure is atomic:** a request that fails saves nothing, so the user can retry. The only partial outcomes are the ones a use case states (an invitation, a notification or an AI call failing after the main save).
5. **Empty lists** are a successful response with no items, not an error.
6. **Subscription gating:** the API decides whether the Owner of the property has an active paid subscription (plan Basic or Pro, paid period running). Without one, gated content (AI classification, payment-pattern summary) is withheld, and the response says so. The rest of the response is unaffected.
7. **AI failure** (error or timeout) never blocks or rolls back saving data (policy: U-8).
8. **Soft delete** keeps history. Soft-deleted records are hidden from normal lists but kept for the history the use cases name.
9. **Transport:** HTTPS only (NFR-08).
10. **Plan limits:** the Owner's plan sets the maximum number of properties and the maximum number of rooms per property (§8.3, UC-31). Adding past a limit is rejected with an error code (UC-10, UC-14). After a downgrade takes effect, the properties and rooms the Owner did not keep are **view-only**: their data, leases and tenants cannot be changed (error codes `PROPERTY_READ_ONLY`, `ROOM_READ_ONLY`), but bills are still generated and payments and complaints are still processed. Responses carry `editable` on properties and rooms so the app does not compute this.

## 7. Account access

*Shared with niscala-app.*

<!-- shared:begin -->
Login and sign-up are preconditions, not use cases. All use cases assume a valid session. The account identifier is **email**.

- **Owner** signs up and logs in with Google or a local password (FR-20).
- **Tenant** activates through an invitation link shared by management. During activation the tenant completes whatever data management left empty, including email and at least 2 emergency contacts if management gave none, then chooses Google or a local password (FR-01).
- **Manager** activates through an invitation link shared by the Owner, enters their own email, and chooses Google or a local password; a person who already has a Manager account can accept the link with that account (FR-26).
- **Profile menu (FR-30):** a Google-only user can add a local password. A password user can link Google, but only after logging in with the password. The app never links accounts automatically by matching email.
- **Local password rules (NFR-11, NIST SP 800-63B Rev. 3, AAL1).** These apply only to accounts with a local password:
    - minimum 8 characters, and at least 64 accepted;
    - no composition rules and no forced periodic change;
    - a show-password toggle while typing;
    - the backend rejects common passwords (a local list), a single repeated character or an ascending/descending run, and passwords containing "niscala" or the user's email local part or name (when ≥ 4 characters). It also rate-limits failed logins. The app's strength meter is a hint only. The app shows these errors in Indonesian, mapped from the error code the API returns.
- **Sessions (FR-33, NFR-18):**
    - a user may be logged in on several devices at once;
    - a user can list their sessions and end the session of one other device or of all other devices (UC-37);
    - after a password change, the user is offered to log out all other devices (UC-38);
    - a session ends after 90 days without use, and at most 1 year after the last authentication regardless of activity; refreshing restarts the 90 days but never the 1 year (longer than the 30-day reauthentication that NIST SP 800-63B Rev. 3, AAL1 recommends, so that tenants who open the app only around due dates are not logged out between visits);
    - a session ended by the user or by Admin stops working within 15 minutes at most.
<!-- shared:end -->

Additional backend rules:

- Rate limiting of failed logins MUST NOT use a puzzle-style CAPTCHA or a "retype the code" check. The API returns an error code the app shows in Indonesian.
- Deactivating or deleting an account ends its sessions (UC-30, UC-34, UC-35).
- **Password blocklist.** Checked on registration, on adding a password and on changing a password, after lowercasing. Reject if the password:
    - is in `data/common-passwords.txt` (top 100,000 from SecLists, MIT; loaded into a set at startup);
    - is one repeated character or an ascending/descending run (`aaaaaaaa`, `12345678`, `abcdefgh`);
    - contains "niscala", or the user's email local part or name (when ≥ 4 characters).

  The error code is `PASSWORD_TOO_COMMON` (422, on the password field). A run must cover the whole password (`12345678`, not `12345679`). At sign-up the password is checked before the email is checked for duplicates.
- **Sessions.** One `sessions` row per device, holding the hashed refresh token, device name, platform, login method, `last_active_at`, `reauthenticated_at` and `revoked_at`. Revoking a session sets `revoked_at`. Access tokens live 15 minutes at most, so a revoked session stops working within 15 minutes. No IP address or location is stored. A session may hold one push token, removed with the session.
- **Tokens.** The access token is a signed JWT valid for 15 minutes at most, sent as `Authorization: Bearer <token>`, and identifies the session. The refresh token is opaque, stored hashed on the `sessions` row, and rotated on every use: the old one stops working at once. Presenting an already-rotated or revoked refresh token ends that session. Refreshing restarts the 90-day idle window and never extends the 1-year cap; a refresh after either limit fails and the session is ended. A failed refresh answers `401` with `REFRESH_TOKEN_INVALID`; the 1-year cap counts from the login that started the session. The backend also checks the session on every request, so an ended session stops working at once, not only after the access token expires. Sign-up, login, activation and refresh return both tokens in the JSON body.
- **Re-authentication.** Some changes need a recent re-authentication of the session. The caller proves they hold the account with their password or, for an account that signs in with Google, a fresh Google ID token of the linked account; the session is then marked re-authenticated for 5 minutes. Failed attempts count toward the same per-email lock as login failures. Changing a property's bank account is the only such change for now.
    - Re-authentication belongs to the session that did it; other sessions of the user are not affected. The 5 minutes count from the moment of the last successful re-authentication, and a change that needs it answers `REAUTHENTICATION_REQUIRED` (403) once they have passed.
    - With the password: a wrong password answers `PASSWORD_INCORRECT` (422, field `password`) and counts toward the lock; while the email is locked the answer is `TOO_MANY_LOGIN_ATTEMPTS` (429) even for the right password; an account without a password answers `PASSWORD_NOT_SET` (409). A successful re-authentication clears the failure count, like a successful login. The account's email must be verified first.
- **Single-use links.** Invitation links last 7 days. Password-reset links last 30 minutes. Both can be used once. Creating a new invitation link or a new reset link invalidates the previous one.
- **Email.** Emails are trimmed and compared case-insensitively. An email belongs to one account.
- **Email verification** applies only to accounts with a local password (Owner sign-up, and Tenant or Manager activation with a password). Accounts created with Google count as verified. Verification uses a 6-digit code emailed to the account, valid 10 minutes, voided after 5 wrong attempts. A new code can be requested once every 60 seconds; requesting one voids the previous. Until the code is confirmed, the account can log in and use only the endpoints needed to verify the email, read its profile and log out; every other endpoint answers `EMAIL_NOT_VERIFIED` (403). Error codes of sign-up, login and verification:
    - `EMAIL_ALREADY_REGISTERED` (409, field `email`): sign-up with an email that belongs to an account;
    - `INVALID_CREDENTIALS` (401): login with an unknown email, a wrong password or an account without a password, all answered the same way;
    - `VERIFICATION_CODE_INVALID` (422, field `code`): wrong code, counted toward the 5 attempts;
    - `VERIFICATION_CODE_EXPIRED` (422, field `code`): no code, an expired code or one voided by 5 wrong attempts;
    - `VERIFICATION_CODE_TOO_SOON` (429, with `Retry-After`): a new code requested within 60 seconds of the last one;
    - `EMAIL_ALREADY_VERIFIED` (409): verification asked for an account that is already verified.

  The code is emailed through an email sender; until a real mail service is chosen it only writes the code to the server log.
- **Google.** The app obtains a Google ID token and sends it; the backend verifies signature, audience and expiry and uses the token's `sub` as the identity. One Google identity belongs to one account. Google login finds the account by that identity, never by email (§7, "never links accounts automatically"). A Google-only account that is asked for a password reset receives nothing. Unlinking Google is not offered.
- **Login failures.** Failed local logins are counted per email address; after 5 failures the address is locked for 15 minutes and login answers `TOO_MANY_LOGIN_ATTEMPTS` with a `Retry-After` header, even for the right password. A successful login before the limit resets the count.
    - The count is kept for any email, registered or not, so the response does not reveal whether an account exists. Emails differing only by case or surrounding spaces share a count.
    - The 5th failure still answers `INVALID_CREDENTIALS` and starts the lock; attempts during the lock answer `TOO_MANY_LOGIN_ATTEMPTS`, do not count and do not extend it. When the lock ends the count starts again from zero.
    - Failures do not age: 4 failures a month ago and 1 now still lock, until a successful login resets the count.
- **Password length.** A new password is 8 to 128 characters; login accepts any non-empty password.
- **Password reset.** Requesting a reset answers the same way whether or not the email is registered. Completing a reset sets the new password (checked against the password rules) and ends every session of the account.
- **Invitation activation.** A public preview endpoint reports the link's state (`valid`, `expired`, `used`) with what the activation screen shows. Activation consumes the link, creates the account, starts a session and, for a local password, requires email verification. On the password path the person types their own email, for a Tenant and a Manager alike; a Google activation uses the Google account's email. The email MUST NOT already belong to another account, except when the person accepts with an existing account (next bullet). For a Tenant whose emergency contacts are still missing, activation MUST receive 2 to 4 contacts.
- **Accepting an invitation with an existing account** needs a session. One account has one role, so an invitation for another role is refused. A Tenant with an active lease cannot accept a Tenant invitation. A logged-in Manager account may accept a Manager invitation; it keeps the assignments from other Owners and gains the new ones. Accepting consumes the link and notifies the inviting Owner. Declining is not a server action: the link stays valid until it expires.
- **Add a local password (profile).** For a Google-only account. The request carries a fresh Google ID token whose identity MUST be the one linked to the account.
- **Link Google (profile).** For an account with a local password. The current session MUST come from a password login (`PASSWORD_LOGIN_REQUIRED` otherwise).
- **Profile.** The profile is read-only for its owner; only an Admin edits an account (UC-34).

## 8. Server-side rules per use case

Same IDs and order as the app's use cases. Only what the backend must enforce or return is listed. Permissions follow §4; "management" means Owner, or Manager on an assigned property.

### 8.1 Tenant (Penyewa)

**UC-01 View room and lease** (FR-02) · Returns the Tenant's room number, facilities, and lease start and end dates, or a result the app can recognise as "no room or lease".

**UC-02 Submit maintenance complaint** (FR-03, FR-04, FR-25, FR-28) · Tenant with an active lease only. Rejects an empty or too-short description with a field error (at least 10 characters after trimming). Saving the complaint MUST NOT depend on the AI result. After saving, the complaint is *Baru* and its classification state is exactly one of:
- a classification (category, urgency, suggested action);
- *Menunggu Klasifikasi*: the AI was attempted and failed or timed out;
- *Belum Diklasifikasi*: the Owner had no active subscription when the complaint was saved, so the AI was skipped.

Optionally, one photo of the problem: JPG or PNG, at most 5 MB; anything else gets a field error. It is attached after the complaint is saved, and the Tenant may attach or replace it while the complaint is *Baru*. A failed upload leaves the complaint saved, and the Tenant can retry.

**UC-03 View complaint status and history** (FR-05) · The Tenant's own complaints, each with its status and classification state. Detail includes category and urgency when classified, and the handling note of each status change. Detail says whether a photo is attached. The Tenant and management can fetch it.

**UC-04 View rent payment history and status** (FR-06) · Tenant with an active lease. Bills and payments with status, period, amount and due date (bill date + grace period). Each bill carries its days overdue: the days past its due date while it is *Belum Bayar* or *Ditolak*, otherwise 0. A bill *Menunggu Verifikasi* is not overdue. Bill detail, for the Tenant and for management, includes the status history: every status the bill has had, starting with its creation. Each entry has the time, the actor (none for the system), whether it was a manual change (UC-09), the reason (for a rejection or a manual change) and, for *Lunas*, the method.

**UC-05 Upload transfer receipt** (FR-07) · Allowed only for the Tenant's current-period payment that is *Belum Bayar* or *Ditolak*, and only when the property has a bank account. Images only: JPG or PNG, at most 5 MB; anything else gets a field error. Returns the property's bank account and the amount to transfer for the upload screen. On success: *Menunggu Verifikasi*.

**UC-06 View notifications** (FR-08) · All roles except Admin. The caller's in-app notifications, newest first, each with a read flag, type, creation time and the facts of the event it announces, as they were when it happened (for example the payment status the notification announces, not the bill's current status). Opening one marks it read; the caller can also mark all as read. Marking an already-read notification read changes nothing. A notification is created and kept even when its push is switched off or fails, and a failure to create or push one never undoes the event that caused it.

Notification types and who receives them:

| Type                   | Recipient                                  | Created when                                                                                                                                                                  |
|------------------------|--------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `billIssued`           | Tenant                                     | A rent bill is generated (timing: U-6).                                                                                                                                       |
| `dueDateReminder`      | Tenant                                     | 3 days before a bill's due date at 07:00, if the bill is still *Belum Bayar* or *Ditolak*. Not sent for a bill issued fewer than 3 days before its due date.                  |
| `billOverdue`          | Tenant; Owner and Managers of the property | At 07:00 on the day after a bill's due date, if the bill is still *Belum Bayar* or *Ditolak*. Once per bill.                                                                  |
| `paymentStatusChanged` | Tenant                                     | Management changes a payment status (UC-07, UC-08, UC-09). Carries the new status, the method for *Lunas*, and the rejection or manual-change reason.                         |
| `complaintStatusChanged` | Tenant                                   | Management moves the Tenant's complaint to a new status (UC-24). Carries the status and the handling note.                                                                    |
| `complaintSubmitted`   | Owner and Managers of the property         | A Tenant submits a complaint (UC-02). Carries urgency and category when classified.                                                                                           |
| `receiptUploaded`      | Owner and Managers of the property         | A Tenant uploads a transfer receipt (UC-05).                                                                                                                                  |
| `cashPaymentRecorded`  | Owner                                      | A Manager records a cash payment (UC-08). Not sent when the Owner records it.                                                                                                 |
| `tenantActivated`      | Owner and Managers of the property         | A Tenant activates their account.                                                                                                                                             |
| `managerActivated`     | Owner                                      | A Manager activates their account.                                                                                                                                            |

A Manager sees only notifications about properties currently assigned to them; a removed assignment hides them immediately. Times are 07:00 in Asia/Jakarta (WIB) for every user. Retention: notifications are kept; there is no automatic deletion.

**Notification settings** (UC-06) · All roles except Admin. Each user has one push on/off switch per notification category, and the settings only control **push** delivery; every notification still appears in the list (UC-06). Categories by role:

| Category            | Roles          | Covers                                                                                                                                                                              |
|---------------------|----------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `billing`           | Tenant         | `billIssued`, `dueDateReminder`, `billOverdue`                                                                                                                                      |
| `paymentStatus`     | Tenant         | `paymentStatusChanged`                                                                                                                                                              |
| `complaintProgress` | Tenant         | `complaintStatusChanged`                                                                                                                                                            |
| `newComplaint`      | Owner, Manager | `complaintSubmitted`; has an urgency scope: `allUrgencies` (default) or `highOnly` (only complaints classified with urgency *Tinggi*; unclassified complaints are not pushed under `highOnly`) |
| `receiptUpload`     | Owner, Manager | `receiptUploaded`                                                                                                                                                                   |
| `overdueBill`       | Owner, Manager | `billOverdue`                                                                                                                                                                       |
| `accountActivity`   | Owner, Manager | `tenantActivated`; and for the Owner also `managerActivated` and `cashPaymentRecorded`                                                                                              |

Defaults: every category on, scope `allUrgencies`. A user who never saved settings gets the defaults. The save replaces the whole resource and MUST contain exactly the categories of the caller's role. Whether the Android OS allows notifications, and per-channel sound or vibration, are handled by the app and the OS and are not stored here.

**Push token.** The app registers its device push token for the current session. One token per session; registering again replaces it. The token stops being used when the session ends (UC-37). Push is sent only for notifications whose category is switched on for that user. Push is delivered through Firebase Cloud Messaging (Android only); the token is the device's FCM registration token.

### 8.2 Management (Pemilik Kost and Pengelola Kost)

Lists are limited to the properties the caller may access: all of an Owner's own, or a Manager's assigned ones.

Every payment-status change (UC-05, UC-07, UC-08, UC-09) triggers regeneration of that Tenant's payment-pattern summary (UC-26). Changes made by management (UC-07, UC-08, UC-09) notify the Tenant (FR-08).

**UC-07 Verify or reject receipt** (FR-08, FR-09) · Lists payments *Menunggu Verifikasi*. Detail returns tenant, room, period, amount and the receipt image.
- Verify: *Menunggu Verifikasi* → *Lunas*. The payment date is the date the receipt was uploaded.
- Reject: requires a rejection reason; *Menunggu Verifikasi* → *Ditolak*. The Tenant may upload again (UC-05).

If notifying the Tenant fails, the status change still stands.

**UC-08 Record cash payment** (FR-08, FR-10) · Management only. For a bill that is *Belum Bayar* or *Ditolak*: takes the period and the date received (an invalid date, or a date after today, gets a field error) → *Lunas*, method *Tunai*.

**UC-09 Change payment status manually** (FR-08, FR-11) · Target status *Belum Bayar*, *Lunas* or *Ditolak*, with a **required** reason. Rejected with a field error if the target equals the current status or the reason is empty. When the target is *Lunas*, the method (*Tunai* or *Transfer*) and the date received are also required, with the same date rule as UC-08. For any other target they MUST be absent; otherwise a field error.

**UC-10 Add property** (FR-12, FR-21) · Owner only. Name and address required. The name MUST be unique within the Owner's account, ignoring case and surrounding spaces; a duplicate gets `PROPERTY_NAME_TAKEN` on the field `name`. The name of a deleted property can be used again. Optional bank account for rent transfers: bank name, account number, account holder name. If any bank-account field is given, all three are required.
The Owner's plan limits the number of properties (Gratis 1, Basic 3, Pro unlimited). Adding a property when the Owner already has that many (view-only ones included, deleted ones excluded) is rejected with `PROPERTY_LIMIT_REACHED` (403).

**UC-11 View properties** (FR-12, FR-21) · Accessible properties, each with name, address, room count, occupied room count and assigned managers. Detail adds the vacant room count and the bank account, if set.

**UC-12 Edit property** (FR-12) · Owner only. Edits name, address and bank account. Rejected with `PROPERTY_READ_ONLY` while the property is view-only (§6 rule 10). Changing the bank account (adding, replacing or removing it) needs a recent re-authentication of the session (§7); otherwise the request is rejected with `REAUTHENTICATION_REQUIRED` and nothing is saved. Editing the name or address does not, and neither does sending the bank account unchanged. Checks run in this order: role, access, view-only, re-authentication, name already taken (the property's own name never counts).

**UC-13 Delete property** (FR-12) · Owner only. Rejected if the property has an active lease. On success the property's rooms and manager assignments are removed too. A view-only property can still be deleted, which frees a place under the plan limit.

**UC-14 Add room** (FR-12) · Fields:
- room number: required, trimmed, MUST be unique within the property ignoring case and surrounding spaces (`ROOM_NUMBER_TAKEN`, field `number`); the number of a deleted room can be used again;
- base rate: required, per month, greater than 0;
- `lengthM` and `widthM`: optional, in metres, each 0 < x ≤ 20 with at most 2 decimals. Both or neither, otherwise a field error on the dimension that is missing. Area is not stored;
- facilities: free-form tags. On save each tag is trimmed, lowercased and has repeated spaces collapsed; duplicates are dropped and empty tags are ignored. At most 30 characters per tag and 15 tags per room, counted after this normalization; going over either gives a field error on `facilities`. They are stored as one text-array column on the room.

The Owner's plan limits the number of rooms per property (Gratis 15, Basic and Pro unlimited). Adding a room when the property already has that many (view-only ones included, deleted ones excluded) is rejected with `ROOM_LIMIT_REACHED` (403). The limit is the plan of the property's Owner, also when a Manager adds the room. Adding to a view-only property is rejected with `PROPERTY_READ_ONLY`. Checks run in this order: role, property access, view-only, field rules, room number taken, room limit.

A suggestions endpoint returns the distinct facility tags already used on rooms of the same Owner (not deleted ones), sorted alphabetically. A Manager gets the tags of the property Owner's rooms, including properties not assigned to them.

**UC-15 View rooms** (FR-12) · The list is in natural order of the room number ("2" before "10"). A room that does not exist, was deleted or belongs to a property the caller cannot access answers `ROOM_NOT_FOUND` (404). Each room with number, base rate, occupancy, dimensions and facilities, plus, if occupied, the Tenant's name and the lease end date. Detail adds the Tenant's phone number, the lease start date and that lease's rent.

**UC-16 Edit room** (FR-12) · Same fields and rules as UC-14. Changing the base rate never changes the rent of existing leases. Rejected with `ROOM_READ_ONLY` (or `PROPERTY_READ_ONLY` for a view-only property) while the room is view-only. Checks run in this order: role, room access, property view-only, room view-only, field rules, room number taken (the room's own number never counts). A room is `editable` only when neither it nor its property is view-only.

**UC-17 Delete room** (FR-12) · Rejected if the room has an active lease. A view-only room, or a room of a view-only property, can still be deleted, which frees a place under the plan limit. Rooms are soft-deleted.

**UC-18 Add tenant** (FR-13) · Required: a room that is *Kosong*, name, phone number. Optional: occupation, emergency contacts, lease dates, billing cycle (default monthly from the lease start date), grace period (default 0), rent.
- Phone number: MUST be an Indonesian mobile number: after removing spaces and dashes, `08` or `628` followed by 8 to 11 digits. Stored and returned as digits starting with `08`.
- Emergency contacts: 2 to 4, each with name, relationship and phone (same phone rule). Management may leave them empty while the account is *Belum Diaktifkan*; the Tenant then completes them during activation, which is rejected until there are 2 to 4 (§7). Exactly 1 contact is rejected with a field error.
- Rent: per billing cycle (the amount of one bill), greater than 0. If omitted on a monthly lease, it is set to the room's base rate; other cycles require it.
- Email is not set here; the Tenant fills it in during activation.
- Rejected with `ROOM_READ_ONLY` (or `PROPERTY_READ_ONLY` for a view-only property) while the room is view-only.

On save the room becomes *Terisi* and an invitation link is created and returned. If link creation fails, the Tenant is still saved and the link can be regenerated (UC-20).

**UC-19 View tenants** (FR-13) · Each Tenant with room number, name, account status, billing cycle and lease end date, plus the invitation expiry while the account is *Belum Diaktifkan*. Detail adds phone, email (once set), occupation, emergency contacts, the lease (dates, rent, billing cycle, grace period, next bill date) and, while the account is *Belum Diaktifkan*, the invitation: when it was created, when it expires, whether it has expired and, if not, its link.

**UC-20 Edit tenant** (FR-13) · Editable: name, phone, occupation, emergency contacts, lease dates, rent, billing cycle, grace period; the same rules as UC-18 apply, and an *Aktif* Tenant's emergency contacts cannot be emptied. The room cannot be changed here. Rejects a lease end date before the start date. A rent or billing-cycle change applies **from the next bill onward**. Rejected with `ROOM_READ_ONLY` (or `PROPERTY_READ_ONLY` for a view-only property) while the room is view-only.
Regenerate invitation link, for an unused or expired invitation (links last 7 days, §7): creates a new link and invalidates the old one. If regeneration fails, the old link stays valid. While an invitation is unused and not expired, its link can be shown again, so the backend keeps it in a form it can return (encrypted, not only hashed).

**UC-21 Delete tenant** (FR-13) · Soft delete: the lease ends, account access is revoked and the room becomes *Kosong*. Payment and complaint history is kept. Rejected with `ROOM_READ_ONLY` (or `PROPERTY_READ_ONLY` for a view-only property) while the room is view-only.

**UC-22 Occupancy dashboard** (FR-14) · Per accessible property: room count, occupied count, vacant count, occupancy percentage and each room's number and occupancy, plus a summary across all accessible properties. All figures are computed here; the app computes none of them.
- A room is *Terisi* when it has an active lease, otherwise *Kosong* (§5).
- Occupancy percentage = occupied rooms ÷ rooms × 100, rounded to the nearest whole number (halves round up). It is 0 when there are no rooms. The summary percentage is computed from the summed counts, never as an average of the properties' percentages.
- Properties are ordered by name and rooms by room number (natural order, so "2" comes before "10").
- No accessible property gives a summary of zeros and an empty `items` list, not an error.
- Subscription state does not change this response.

**UC-23 Complaint list with AI classification** (FR-15, FR-25) · Complaints across accessible properties, sorted by urgency, then time. Includes category, urgency and suggested action when available; otherwise the classification state. Without an active subscription, AI classification results are withheld (§6 rule 6); manual classifications (UC-36) are not. A withheld AI result is flagged as withheld, so the app can tell it apart from an unclassified complaint. A manual classification also returns who set it and the original AI result it replaced, if any. The original AI result is withheld like any AI result.

**UC-24 Change complaint status** (FR-16) · The target MUST be the next status: *Baru* → *Diproses*, or *Diproses* → *Selesai*. Any other target is rejected, and so is any change once the complaint is *Selesai*. An optional handling note is stored with the change and returned to the Tenant (UC-03).

**UC-36 Classify complaint manually** (FR-32) · Management sets category and urgency on a complaint whose classification state is *Menunggu Klasifikasi* or *Belum Diklasifikasi*, or corrects an AI classification. The category MUST be one of the complaint categories, which an endpoint returns (list contents: U-16).
- Stored: the original AI result (if any), the manual values, the actor and the timestamp.
- An AI result that arrives after a manual classification is stored only as the original AI result; it never overwrites the manual values.
- No active subscription is required; this is not an AI feature.
- Submitting the current values changes nothing.

**UC-25 Payment status of all tenants** (FR-17) · For a property and a date (default: today): each Tenant with room and the bill whose period contains that date, with its amount and payment status, or none. Each Tenant's payment history is the list of their bills.

**UC-26 Payment-pattern summary** (FR-18, FR-19, FR-25, FR-28) · For every Tenant:
- rule-computed facts over the Tenant's **counted bills**: the last 6 bills, by due date, that are *Lunas* or overdue (UC-04). A counted bill is **late** if it was paid after its due date or is overdue.
    - on-time count and counted-bill count (e.g. 4 of 6);
    - average days late: the mean days late of the late counted bills, rounded to the nearest whole day. A bill paid late counts the days from its due date to its payment date; an overdue bill counts its days overdue so far. 0 if there are none;
    - arrears: the total amount of all the Tenant's overdue bills.
- an at-risk flag: at least 2 late counted bills, or any bill more than 7 days overdue;
- the stored AI summary, or none yet.

Without an active subscription, facts and flags are returned and the summary is withheld. Reading this data never triggers AI generation; summaries are regenerated when a payment status changes.

### 8.3 Owner only (Pemilik Kost)

**UC-27 Add manager** (FR-22) · Owner only. Required: name, phone (WhatsApp) and at least one property; every property MUST belong to the Owner.
- Phone number: the same rule as UC-18 (Indonesian mobile number, `08` or `628` followed by 8 to 11 digits after removing spaces and dashes; stored and returned as digits starting with `08`).
- Email is not set here and nothing is emailed; the Manager types their own email during activation (§7), so a Manager's email is empty until then.

The account is created as *Belum Diaktifkan* and an invitation link is created and returned: single use, expiring 7 days after creation (§7). The Owner shares the link (copy, WhatsApp or QR). The response returns the Manager with the invitation.

**UC-28 View managers** (FR-22) · Owner only. Each Manager with name, phone, email (once set), assigned properties (id, name, address) and account status; the list can be limited to one property. Detail adds, while the account is not *Aktif*, the invitation: when it was created, when it expires, whether it has expired and, if not, its link. While an invitation is unused and not expired its link can be shown again, so the backend keeps it in a form it can return (as for UC-20).

**UC-29 Edit manager** (FR-22) · Owner only. Replaces name, phone (same rule as UC-27) and assigned properties, keeping at least one property. Access to removed properties is revoked at once. Email is not edited here.
Regenerate invitation link: only for a Manager that is not yet *Aktif*; it creates a new link and invalidates the old one, and for an expired invitation it renews it. For an *Aktif* Manager it is rejected.

**UC-30 Delete manager** (FR-22) · Owner only. Revokes this Owner's property assignments for the Manager and keeps the Manager's account. When no assignments from any Owner remain, the account is soft-deleted and its sessions end. The Manager's action history is kept.

**UC-31 Choose subscription plan** (FR-23, FR-25) · Owner only. Returns the plans and the current subscription.
- Plans (server data, so prices and limits can change without an app release): Gratis (1 property, 15 rooms per property, no AI features, free), Basic (3 properties, unlimited rooms, AI features, Rp49.000 per month or Rp490.000 per year), Pro (unlimited properties, unlimited rooms, AI features, Rp129.000 per month or Rp1.290.000 per year). Each paid price carries its Google Play product id and base plan id.
- Current subscription: plan, status (*Gratis* or *Aktif*), billing period and end date while *Aktif*, whether it renews automatically, the number of properties in use, the open order *Menunggu Pembayaran* if any, and the scheduled downgrade if any.
- **Upgrade or first purchase:** confirming a paid plan and billing period creates an order *Menunggu Pembayaran*. Only a plan higher than the current one is accepted (`SUBSCRIPTION_NOT_AN_UPGRADE` otherwise). A new order expires any earlier open order of the Owner.
- **Downgrade** (to Basic from Pro, or to Gratis): takes effect at the end of the paid period; until then the current plan stays fully active. The renewal itself is stopped or changed in Google Play. Before that, the Owner confirms which properties stay editable: exactly the target plan's limit, or all of them if the Owner has fewer (`KEPT_PROPERTIES_INVALID`). For Gratis the Owner also confirms which rooms of the kept property stay editable: exactly 15, or all if it has fewer (`KEPT_ROOMS_INVALID`). The confirmation is stored as the scheduled downgrade and can be replaced or cancelled. At the end of the period, everything not kept becomes view-only (§6 rule 10). If the Owner made no confirmation, the backend keeps the earliest-created properties and, for Gratis, the occupied rooms first, then the lowest room numbers. Upgrading again makes everything editable again.

**UC-32 Pay for subscription** (FR-24, FR-25, FR-27) · Owner only. Payment runs through Google Play Billing. The app performs the purchase on the device and sends the purchase token for the order; the backend never charges money itself. Until this is built, a development command grants an Owner a paid period (`niscala-api grant-subscription`, see `README.md`); it is not an API endpoint and is not part of the contract.

The Owner's **effective plan** is the stored paid plan while its period has not ended (the end time is strictly in the future), otherwise Gratis. The plan limits and AI availability of UC-31 are read from it.
- The backend verifies the token with the Google Play Developer API, checks that the purchased product matches the order and that the token is not already used by another Owner, acknowledges the purchase, and sets the subscription from Google's data (plan, billing period, end date, renewal).
- *Berhasil* (purchase completed) → the order is *Berhasil* and the subscription is *Aktif* at once;
- pending at Google (for example pay at a convenience store) → stays *Menunggu Pembayaran* and can be re-checked by sending the token again; verification is idempotent;
- *Gagal* (Google reports the purchase failed or canceled) or *Kedaluwarsa* (the purchase never completed in time) → the Owner may pay again with a new order.
- A purchase cancelled by the Owner in the Google Play sheet never reaches the backend; its order stays *Menunggu Pembayaran* until it expires or a new order replaces it.
- If Google Play is unreachable, return an error (`GOOGLE_PLAY_UNREACHABLE`); the order is unchanged and the token can be sent again.
- Renewal, cancellation, refunds and plan changes happen in Google Play. The backend reflects them from Google's data (how and when: TBD-3).

### 8.4 Admin

**UC-33 View user accounts** (FR-29) · Admin only. All accounts of every role, each with name, email, role (*Penyewa*, *Pemilik Kost*, *Pengelola Kost*, *Admin*) and status. Search by email (case-insensitive, matches any part of the current email) and filter by role; no match is an empty result. *Dihapus* accounts are hidden unless the caller asks for them. Detail adds the registration time, the login methods, the last login time, any pending email change and what the account is linked to: the properties an Owner owns or a Manager is assigned to, the number of active leases, and a Tenant's property, room and lease end date. Accounts that have not been activated yet are not listed.

**UC-34 Edit user account** (FR-29) · Admin only. Changes name, email and status. The email MUST be unique among all accounts, deleted ones included; a duplicate gets a field error. The status is *Aktif* or *Nonaktif*; a *Nonaktif* account can be set back to *Aktif* at any time.
- Deactivating ends the account's sessions (they stop working within 15 minutes, §7). A deactivated account cannot log in. Its data and bills continue as before.
- An Admin cannot deactivate their own account (`CANNOT_MODIFY_OWN_ACCOUNT`). Editing their own name or email, and any action on other Admins, is allowed.
- An email change does not take effect at once. The backend sends a single-use verification link to the new address and a notice to the current one. The link is valid for 7 days. Until the link is confirmed the account keeps logging in with the current email, and the response carries the new address as the pending email with its expiry. Confirming the link replaces the email and clears the pending one.
- Submitting the current email while a change is pending cancels the pending change.
- Submitting the current values changes nothing.
- A *Dihapus* account cannot be edited.

**UC-35 Delete user account** (FR-29) · Admin only. Soft delete that ends the account's sessions and cannot be undone from the app. An Admin cannot delete their own account (`CANNOT_MODIFY_OWN_ACCOUNT`); other Admins can be deleted. Rejected, each with its own error code, if the account is:
- an Owner with a property that has an active lease (`OWNER_HAS_ACTIVE_LEASE`);
- a Tenant with an active lease (`TENANT_HAS_ACTIVE_LEASE`).

Deleting an Owner archives their properties, rooms and the Managers' assignments to them (hidden and read-only, history kept). Deleting a Manager revokes their assignments. Payment and complaint history is kept in every case. An account already deleted through UC-21 or UC-30 is also *Dihapus* here. Deleting an already deleted account is rejected (`USER_ACCOUNT_DELETED`).

### 8.5 All roles

**UC-37 Manage active sessions** (FR-33, NFR-18) · Lists the caller's active sessions (not ended, not past the idle or 1-year limit (§7)), most recently active first. Each has device name, platform, login method (`google` or `password`) and last activity, and flags the current one (the session of the request). The platform is free text sent by the app at login (for example "Android 14"); the backend stores it as given and never branches on it. The caller can end the session of one other device or of all other devices. The current session is not ended here; it ends through normal logout.
- Ending a session sets its `revoked_at`; it stops working within 15 minutes (§7).
- Ending one session: a session that does not exist, is already ended, or belongs to another user gets the same not-found error (error code `SESSION_NOT_FOUND`). The current session gets `SESSION_IS_CURRENT`.
- Ending all other sessions with none to end is a success. Both end calls respond with no body.
- Available to every role and only on the caller's own sessions.

**UC-38 Change password** (FR-33, NFR-11) · Takes the current password and a new one. The new password is checked against the §7 rules; the confirmation field is app-only. Errors, each with its error code and the field it belongs to:
- wrong current password: `CURRENT_PASSWORD_INCORRECT` (field `currentPassword`);
- new password shorter than 8 or longer than 128 characters: field error on `newPassword`;
- blocklisted (§7): `PASSWORD_TOO_COMMON`;
- same as the current password: `PASSWORD_UNCHANGED`;
- account has no local password (Google only): `PASSWORD_NOT_SET`; the user adds one from the profile menu first (§7);
- too many failed attempts: `TOO_MANY_ATTEMPTS`.

The current session stays logged in. The response says whether the user has other active sessions (`hasOtherSessions`), so the app can offer to end them (UC-37). Ending them is a separate call.

## 9. API contract

This repository owns the contract. The OpenAPI document FastAPI generates from the code is the source; the app generates a Dart client from it and never hand-edits it. A breaking change (removed or renamed path, field or enum value, changed type) is released together with an app PR.

Conventions:

- Field names are the glossary code names (§3) in camelCase.
- Enum values are the §5 codeNames, except Baru, whose value is `new`.
- Dates are `YYYY-MM-DD`; timestamps are ISO 8601 in UTC with `Z`.
- Money is an integer number of rupiah.
- Room dimensions are JSON numbers.
- IDs are UUID strings.
- A list response is an object with an `items` array, so pagination or totals can be added without a breaking change.
- An edit is a `PUT` of the full resource.
- Role values are the lower-case code names: `tenant`, `owner`, `manager`, `admin`.
- A query parameter that filters a list is optional; omitting it means no filter.
- Authentication: an HTTP bearer scheme named `bearerAuth` (JWT access token) is declared on every operation except `GET /health` and the endpoints marked *public* below.
- Error responses have the shape in §6 rule 2. They are not declared in the OpenAPI document yet (U-9).

Endpoints:

| Method   | Path                                            | Purpose                                                   | Used by                                                   |
|----------|-------------------------------------------------|-----------------------------------------------------------|-----------------------------------------------------------|
| `GET`    | `/health`                                       | Confirms the API is up and its database connection works. | Walking skeleton (NKMA-6): the app displays the response. |
| `POST`   | `/properties`                                   | Add property.                                             | UC-10                                                     |
| `GET`    | `/properties`                                   | List accessible properties.                               | UC-11                                                     |
| `GET`    | `/properties/{propertyId}`                      | Property detail.                                          | UC-11                                                     |
| `PUT`    | `/properties/{propertyId}`                      | Edit property.                                            | UC-12                                                     |
| `DELETE` | `/properties/{propertyId}`                      | Delete property.                                          | UC-13                                                     |
| `POST`   | `/properties/{propertyId}/rooms`                | Add room.                                                 | UC-14                                                     |
| `GET`    | `/properties/{propertyId}/rooms`                | List the property's rooms.                                | UC-15                                                     |
| `GET`    | `/properties/{propertyId}/facility-suggestions` | Facility tags already used on rooms of the property's Owner. | UC-14, UC-16                                           |
| `GET`    | `/rooms/{roomId}`                               | Room detail.                                              | UC-15                                                     |
| `PUT`    | `/rooms/{roomId}`                               | Edit room.                                                | UC-16                                                     |
| `DELETE` | `/rooms/{roomId}`                               | Delete room.                                              | UC-17                                                     |
| `POST`   | `/properties/{propertyId}/tenants`              | Add tenant; returns the invitation link.                  | UC-18                                                     |
| `GET`    | `/properties/{propertyId}/tenants`              | List the property's tenants.                              | UC-19                                                     |
| `GET`    | `/tenants/{tenantId}`                           | Tenant detail.                                            | UC-19                                                     |
| `PUT`    | `/tenants/{tenantId}`                           | Edit tenant.                                              | UC-20                                                     |
| `DELETE` | `/tenants/{tenantId}`                           | Delete tenant.                                            | UC-21                                                     |
| `POST`   | `/tenants/{tenantId}/invitation`                | Regenerate the invitation link.                           | UC-20                                                     |
| `POST`   | `/managers`                                     | Add manager; returns the invitation link.                 | UC-27                                                     |
| `GET`    | `/managers`                                     | List the Owner's managers, optionally by `propertyId`.    | UC-28                                                     |
| `GET`    | `/managers/{managerId}`                         | Manager detail with the invitation while not active.      | UC-28                                                     |
| `PUT`    | `/managers/{managerId}`                         | Edit manager.                                             | UC-29                                                     |
| `DELETE` | `/managers/{managerId}`                         | Delete manager.                                           | UC-30                                                     |
| `POST`   | `/managers/{managerId}/invitation`              | Regenerate the invitation link (not yet active only).     | UC-29                                                     |
| `POST`   | `/complaints`                                   | Submit a complaint; returns it with its classification state. | UC-02                                                 |
| `GET`    | `/complaints`                                   | List the caller's complaints (Tenant: own; management: accessible properties). | UC-03, UC-23                         |
| `GET`    | `/complaints/{complaintId}`                     | Complaint detail with its status history.                 | UC-03, UC-23                                              |
| `POST`   | `/complaints/{complaintId}/status-changes`      | Move a complaint to its next status, with an optional handling note. | UC-24                                          |
| `PUT`    | `/complaints/{complaintId}/classification`      | Set or correct the category and urgency manually.         | UC-36                                                     |
| `PUT`    | `/complaints/{complaintId}/photo`               | Attach or replace the complaint photo (multipart, JPG or PNG, at most 5 MB). | UC-02                                  |
| `GET`    | `/complaints/{complaintId}/photo`               | The complaint photo.                                      | UC-03, UC-23                                              |
| `GET`    | `/complaint-categories`                         | The allowed complaint categories.                         | UC-36                                                     |
| `GET`    | `/me/lease`                                     | The calling Tenant's room and lease, or none.             | UC-01                                                     |
| `GET`    | `/rent-bills`                                   | List rent bills (Tenant: own; management: accessible properties), optionally by `tenantId` and `paymentStatus`. | UC-04, UC-07, UC-25 |
| `GET`    | `/rent-bills/{rentBillId}`                      | Rent bill detail with the property's bank account.        | UC-04, UC-05, UC-07                                       |
| `PUT`    | `/rent-bills/{rentBillId}/receipt`              | Upload a transfer receipt (multipart, JPG or PNG, at most 5 MB). | UC-05                                              |
| `GET`    | `/rent-bills/{rentBillId}/receipt`              | The receipt image.                                        | UC-07                                                     |
| `POST`   | `/rent-bills/{rentBillId}/verification`         | Verify a receipt.                                         | UC-07                                                     |
| `POST`   | `/rent-bills/{rentBillId}/rejection`            | Reject a receipt, with a required reason.                 | UC-07                                                     |
| `POST`   | `/rent-bills/{rentBillId}/cash-payment`         | Record a cash payment.                                    | UC-08                                                     |
| `POST`   | `/rent-bills/{rentBillId}/status-changes`       | Change the payment status manually, with a required reason. | UC-09                                                   |
| `GET`    | `/properties/{propertyId}/payment-overview`     | Each Tenant's bill covering a date (`date`, default today). | UC-25                                                   |
| `GET`    | `/properties/{propertyId}/payment-patterns`     | Each Tenant's payment-pattern facts, at-risk flag and AI summary. | UC-26                                             |
| `POST`   | `/auth/register`                                | Public. Owner sign-up with a local password; starts a session. | FR-20                                                     |
| `POST`   | `/auth/register/google`                         | Public. Owner sign-up with Google; starts a session.      | FR-20                                                     |
| `POST`   | `/auth/login`                                   | Public. Log in with email and password; starts a session. | FR-20, FR-26, FR-01                                       |
| `POST`   | `/auth/login/google`                            | Public. Log in with Google; starts a session.             | FR-20, FR-26, FR-01                                       |
| `POST`   | `/auth/refresh`                                 | Public. Exchange a refresh token for a new token pair.    | NFR-18                                                    |
| `POST`   | `/auth/logout`                                  | End the current session.                                  | FR-33                                                     |
| `POST`   | `/auth/email-verification`                      | Send, or resend, the email verification code.             | FR-20, FR-26, FR-01                                       |
| `POST`   | `/auth/email-verification/confirmation`         | Confirm the email with the 6-digit code.                  | FR-20, FR-26, FR-01                                       |
| `POST`   | `/auth/password-reset-requests`                 | Public. Email a password-reset link.                      | NFR-11                                                    |
| `POST`   | `/auth/password-reset-previews`                 | Public. Check a reset link and return the account email.  | NFR-11                                                    |
| `POST`   | `/auth/password-resets`                         | Public. Set a new password with a reset link; ends all sessions. | NFR-11                                                    |
| `POST`   | `/invitations/previews`                         | Public. What an invitation link is for and whether it is still valid. | FR-01, FR-26                                              |
| `POST`   | `/invitations/activations/password`             | Public. Activate an invitation with a local password; starts a session. | FR-01, FR-26                                              |
| `POST`   | `/invitations/activations/google`               | Public. Activate an invitation with Google; starts a session. | FR-01, FR-26                                              |
| `POST`   | `/invitations/acceptance-previews`              | Check whether the caller's account can accept an invitation. | FR-01, FR-26                                              |
| `POST`   | `/invitations/acceptances`                      | Accept an invitation with the caller's existing account.  | FR-01, FR-26                                              |
| `GET`    | `/me`                                           | The caller's account and sign-in methods.                 | FR-30                                                     |
| `POST`   | `/me/local-password`                            | Add a local password to a Google account.                 | FR-30                                                     |
| `POST`   | `/me/google-link`                               | Link a Google account to a password account.              | FR-30                                                     |
| `GET`    | `/me/sessions`                                  | List the caller's active sessions; the current one is flagged. | UC-37                                                     |
| `DELETE` | `/me/sessions/{sessionId}`                      | End the session of one other device.                      | UC-37                                                     |
| `DELETE` | `/me/sessions`                                  | End the sessions of all other devices.                    | UC-37                                                     |
| `POST`   | `/me/password-changes`                          | Change the caller's password; says whether other sessions exist. | UC-38                                                     |
| `GET`    | `/occupancy-dashboard`                          | Occupancy figures per accessible property and across all of them. | UC-22                                                     |
| `GET`    | `/notifications`                                | List the caller's notifications, newest first, with the unread count. | UC-06                                                     |
| `POST`   | `/notifications/{notificationId}/read`          | Mark one notification read; returns it.                   | UC-06                                                     |
| `POST`   | `/notifications/read-all`                       | Mark all of the caller's notifications read.              | UC-06                                                     |
| `GET`    | `/me/notification-settings`                     | The caller's push settings, one entry per category of their role. | UC-06                                                     |
| `PUT`    | `/me/notification-settings`                     | Replace the caller's push settings.                       | UC-06                                                     |
| `PUT`    | `/me/push-token`                                | Register the current session's device push token.         | UC-06                                                     |
| `GET`    | `/user-accounts`                                | List user accounts, optionally by `email` (substring), `role` and `includeDeleted` (default false). Admin only. | UC-33      |
| `GET`    | `/user-accounts/{userAccountId}`                | User account detail. Admin only.                          | UC-33                                                     |
| `PUT`    | `/user-accounts/{userAccountId}`                | Edit name, email and status. A new email stays pending until verified. Admin only. | UC-34                            |
| `DELETE` | `/user-accounts/{userAccountId}`                | Soft-delete an account. Admin only.                       | UC-35                                                     |
| `GET`    | `/subscription-plans`                                  | The available plans with limits, AI availability and prices.   | UC-31 |
| `GET`    | `/subscription`                                        | The Owner's current subscription.                              | UC-31 |
| `POST`   | `/subscription/orders`                                 | Create an order for a paid plan and billing period.            | UC-31 |
| `GET`    | `/subscription/orders/{orderId}`                       | An order with its status.                                      | UC-32 |
| `POST`   | `/subscription/orders/{orderId}/purchase-verification` | Verify the Google Play purchase token of an order.             | UC-32 |
| `PUT`    | `/subscription/scheduled-downgrade`                    | Confirm a downgrade and the properties and rooms that stay editable. | UC-31 |
| `DELETE` | `/subscription/scheduled-downgrade`                    | Cancel the scheduled downgrade.                                | UC-31 |
| `POST`   | `/me/reauthentication/password`                        | Re-authenticate the current session with the password.         | UC-12 |
| `POST`   | `/me/reauthentication/google`                          | Re-authenticate the current session with a Google ID token.    | UC-12 |

Every endpoint listed above except `GET /health` and the implemented ones is declared in the contract but not implemented yet; it responds `501 Not Implemented`. Implemented so far: `POST /auth/register`, `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`, `POST /auth/email-verification`, `POST /auth/email-verification/confirmation`, `GET /me`, `POST /me/reauthentication/password`, `POST /properties`, `GET /properties`, `GET /properties/{propertyId}`, `PUT /properties/{propertyId}`, `DELETE /properties/{propertyId}`, `POST /properties/{propertyId}/rooms`, `GET /properties/{propertyId}/rooms`, `GET /properties/{propertyId}/facility-suggestions`, `GET /rooms/{roomId}`, `PUT /rooms/{roomId}`, `DELETE /rooms/{roomId}`.

The response shape of `/health` is undecided (U-1).

Property and room responses carry `editable` (false while view-only after a downgrade, §6 rule 10).

## 10. Undecided — do not implement by assumption

When work touches one of these items, stop and raise it in Plan mode. Items that also affect the app are listed in its `docs/SPEC.md` §10 with the same ID.

| ID    | Item                                                                                                                             | Affects                   |
|-------|----------------------------------------------------------------------------------------------------------------------------------|---------------------------|
| TBD-3 | Google Play server-side integration: how the backend learns of renewals, cancellations, expiry and refunds (real-time developer notifications endpoint, its authentication, scheduled reconciliation), service account, test environment. | UC-31, UC-32 |
| U-1   | `/health` response shape.                                                                                                        | §9, NKMA-22               |
| U-4   | Invitation and password-reset link handling: how a link opens the app (Android App Links / deep link) and what happens if the app is not installed. | UC-18, UC-20, FR-01, NFR-11 |
| U-6   | Bill generation (FR-31): when bills are created, how the amount is set, and proration.                                           | UC-04, UC-08, UC-25       |
| U-8   | AI calls: timeout, retries, fallback, and whether classification runs within the save request or after it.                       | UC-02, UC-26              |
| U-9   | The complete list of error codes, and declaring error responses in the OpenAPI document. (The response shape is decided, §6 rule 2.) | §6, §7, all endpoints |
| U-15  | How conflicting writes are detected.                                                                                             | §6                        |
| U-16  | Complaint category list contents (the prototype list is placeholder data). Served by `GET /complaint-categories`, so the contract does not change when it is decided. | UC-02, UC-23, UC-36 |
| U-23  | Push delivery through Firebase Cloud Messaging: retry policy and removal of invalid tokens. The contract carries an opaque token string, so it does not depend on this. | UC-06 |

## 11. Changelog

| Date       | Change                                                                                                                    | Decided in |
|------------|---------------------------------------------------------------------------------------------------------------------------|------------|
| 15-10-2026 | Initial version, derived from the app's `docs/SPEC.md` and requirements baseline v1.1 (11-10-2026). Shared blocks marked. | NKMA-14    |
| 15-10-2026 | U-9 partly decided: API messages are English with error codes; the app maps codes to Indonesian.                          | NKMA-14    |
| 16-10-2026 | SRS v1.1 revision: Owner-only property writes and per-property bank account; room base rate, dimensions, facilities; rent per lease; complaint status split from classification state, one-step flow, urgency values, handling note, manual classification (UC-36); receipt JPG/PNG up to 5 MB; sessions (UC-37, UC-38); password blocklist. U-2 decided; U-10, U-14 narrowed; U-16, U-19, U-21 added. | NKMA-96 |
| 16-10-2026 | U-10 decided: camelCase fields, codeName enum values, ISO 8601 dates, integer rupiah, UUID ids, wrapped lists, full-resource `PUT`. UC-10, UC-11, UC-14, UC-15 extended; property and room endpoints added to §9. | NKMA-7 |
| 17-10-2026 | U-21 decided: rent is per billing cycle; base rate pre-fills monthly leases only. Billing cycle values added to §5. Activation requires 2 to 4 emergency contacts (§7). UC-18 to UC-20 extended with phone format, occupation, emergency contacts, list and detail fields and invitation re-sharing; tenant endpoints added to §9. | NKMA-8 |
| 17-10-2026 | U-3 decided: complaint description at least 10 characters. U-16 narrowed: categories are server data from an endpoint. Withheld AI classification flagged on the wire. Complaint endpoints added to §9. | NKMA-16 |
| 17-10-2026 | UC-25 period defined as the bill covering a date. Lease and rent-bill endpoints added to §9. | NKMA-8 |
| 17-10-2026 | Optional complaint photo added (UC-02, UC-03). Manual classifications return the actor and the original AI result (UC-23). Complaint photo endpoints added to §9. | NKMA-16 |
| 17-10-2026 | U-7 decided: payment-pattern facts and at-risk threshold (UC-26). Bills carry days overdue and a status history; a manual *Lunas* takes a method and a date; payment dates cannot be after today. Payment-pattern endpoint added to §9. | NKMA-8 |
| 17-10-2026 | UC-26 average days late includes overdue counted bills. §9 lists the payment-pattern endpoint as not implemented. | NKMA-8 |
| 17-10-2026 | U-13 decided: invitation links last 7 days, password-reset links 30 minutes, both single-use. U-14 decided: JWT access token (15 minutes), opaque rotating refresh token, bearer transport, both in JSON bodies. Email verification by 6-digit code for local-password accounts, gating other endpoints until confirmed. Failed logins lock an email for 15 minutes after 5 failures. Passwords are 8 to 128 characters. Invitation activation takes the person's own email for Tenant and Manager; an existing Manager account may accept a Manager invitation. U-4 extended to password-reset links. Account-access endpoints added to §9. | NKMA-15 |
| 17-10-2026 | UC-37 and UC-38 detailed: session list fields and order, not-found and current-session errors, password change errors and `hasOtherSessions`. Login method values added to §5. Session and password endpoints added to §9. | NKMA-15 |
| 17-10-2026 | Manager use cases UC-27 to UC-30 detailed: managers are added with name, phone and properties and join through a shared invitation link (nothing is emailed); statuses reduced to *Belum Diaktifkan* and *Aktif*; an existing Manager account can accept; invitation regeneration; delete revokes this Owner's assignments and keeps the account. Manager endpoints added to §9. | NKMA-7 |
| 17-10-2026 | UC-22 extended: room count, occupancy percentage rule (whole number, halves up, 0 without rooms, summary from summed counts), ordering and empty result. Occupancy-dashboard endpoint added to §9. | NKMA-7 |
| 17-10-2026 | U-12 decided: due-date reminder 3 days before the due date at 07:00 Asia/Jakarta. UC-06 extended to Owner and Manager, with notification types, recipients and creation rules; notification settings (push on/off per category, urgency scope for new complaints) and push token added under UC-06. Notification endpoints added to §9. Push provider decided: Firebase Cloud Messaging. U-23 added for the remaining push delivery questions. | NKMA-63 |
| 17-10-2026 | Admin account management (UC-33 to UC-35) defined: *Nonaktif* is a reversible suspension, *Dihapus* status added to the Admin account vocabulary, deleted accounts hidden from the default list, delete also rejected for a Tenant with an active lease, an Admin cannot deactivate or delete their own account, an Admin email change stays pending until the new email is verified (link single use, 7 days). `UserAccount` added to the glossary. User-account endpoints added to §9. | NKMA-18 |
| 17-10-2026 | Subscription decided: plans Gratis, Basic and Pro with limits and prices; billing through Google Play Billing with server-side purchase verification; downgrades at period end with kept properties and rooms; property and room limits added to UC-10 and UC-14; order statuses mapped to Google Play. TBD-3 narrowed, U-11 decided. Subscription endpoints added to §9. | NKMA-17 |
| 18-10-2026 | Session lifetime relaxed: a session ends after 90 days without use or 1 year after the last authentication, instead of a fixed 30 days, so that users are not forced to log in about once a month. | NKMA-15 |
| 18-10-2026 | Re-authentication added: changing a property's bank account needs the session to have re-authenticated with the password or Google within the last 5 minutes. Re-authentication endpoints added to §9. | NKMA-15 |
| 18-10-2026 | U-9 narrowed: every error is a single object `{code, field, message}`; validation failures are `VALIDATION_FAILED` on the first invalid field. The code list and OpenAPI declaration stay open. | NKMA-19 |
| 18-10-2026 | U-19 decided: facility tags are stored as a text-array column on the room. | NKMA-20 |
| 18-10-2026 | Token handling implemented: failed refresh answers `REFRESH_TOKEN_INVALID`; the 1-year cap counts from login; the session is checked on every request so ending it takes effect at once. Refresh, logout and profile endpoints marked implemented in §9. | NKMA-30 |
| 18-10-2026 | Owner sign-up, login and email verification implemented: error codes listed in §7, verification code emailed through a sender that only logs it for now. Endpoints marked implemented in §9. | NKMA-31 |
| 18-10-2026 | Password blocklist and login rate limit implemented: runs must cover the whole password, the password is checked before the duplicate email, the failed-login count is kept per email whether or not an account exists, and the 5th failure starts the lock. | NKMA-34 |
| 18-10-2026 | Access guard defined: order of the 401, email-not-verified and forbidden checks; a property the caller cannot access answers `PROPERTY_NOT_FOUND` like a missing one; properties are soft-deleted. | NKMA-36 |
| 18-10-2026 | Effective plan defined (paid plan while its period runs, else Gratis); a development command grants a paid period until Google Play billing exists. | NKMA-76 |
| 18-10-2026 | Re-authentication with the password implemented: per session, valid 5 minutes, shares the failed-login lock, error codes `PASSWORD_INCORRECT`, `PASSWORD_NOT_SET` and `REAUTHENTICATION_REQUIRED`. | NKMA-15 |
| 18-10-2026 | Property endpoints (UC-10 to UC-13) implemented: names are unique ignoring case and surrounding spaces and reusable after deletion, `PROPERTY_NAME_TAKEN`, `PROPERTY_LIMIT_REACHED` answers 403, order of the edit checks, an unchanged bank account needs no re-authentication. Property endpoints marked implemented in §9. | NKMA-37 |
| 18-10-2026 | Room endpoints (UC-14 to UC-17) implemented: room numbers unique ignoring case and reusable after deletion, normalization and limits of facility tags, `ROOM_NUMBER_TAKEN`, `ROOM_LIMIT_REACHED` answers 403, `ROOM_NOT_FOUND`, natural order of room numbers, order of the checks, rooms are soft-deleted, property room counts are real and deleting a property deletes its rooms. | NKMA-41 |

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
- Two AI features set the product apart. Both are available only when the property owner has an active subscription:
    1. classification of maintenance complaints (category, urgency, suggested action);
    2. a natural-language summary of each tenant's payment pattern.
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
| Langganan (Subscription)                            | `Subscription`            | The Owner's paid plan that unlocks AI features.                                    |
| Sesi (Session)                                      | `Session`                 | One logged-in device of a user.                                                    |
| Soft delete (Soft delete)                           | —                         | Marked inactive; history is kept.                                                  |
<!-- shared:end -->

The code names above are used in PEP 8 form in this repository (see `CLAUDE.md`, "Vocabulary"). Their wire form is set in §9.

## 4. Roles and permissions

*Shared with niscala-app.*

<!-- shared:begin -->
`✓` allowed · `A` only on properties assigned to the Manager · `—` not allowed

| Capability                                                   | Tenant | Owner | Manager | Admin |
|--------------------------------------------------------------|:------:|:-----:|:-------:|:-----:|
| View own room, lease, payments, complaints, notifications    |   ✓   |   —   |    —    |   —   |
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

Each role sees only the menus it is allowed to use. The backend enforces permissions; the app hides what a role cannot do.
<!-- shared:end -->

The API checks every request against this table. `A` means the check includes the Manager's current property assignments, so a removed assignment (UC-29) or a deleted Manager (UC-30) loses access immediately.

## 5. Status vocabularies

*Shared with niscala-app.*

<!-- shared:begin -->
| Entity                           | Statuses — Indonesian label (English, `codeName`)                                                                                                                                                                     |
|----------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Room occupancy                   | Terisi (Occupied, `occupied`) · Kosong (Vacant, `vacant`)                                                                                                                                                             |
| Payment                          | Belum Bayar (Unpaid, `unpaid`) · Menunggu Verifikasi (Awaiting verification, `awaitingVerification`) · Lunas (Paid, `paid`) · Ditolak (Rejected, `rejected`)                                                          |
| Payment method                   | Transfer (Bank transfer, `transfer`) · Tunai (Cash, `cash`)                                                                                                                                                           |
| Billing cycle                    | Mingguan (Weekly, `weekly`) · Bulanan (Monthly, `monthly`) · 3 Bulan (Quarterly, `quarterly`) · 6 Bulan (Semiannual, `semiannual`) · 12 Bulan (Annual, `annual`) |
| Complaint                        | Baru (New, `new_`) · Diproses (In progress, `inProgress`) · Selesai (Done, `done`) |
| Complaint classification         | Menunggu Klasifikasi (Awaiting classification, `awaitingClassification`) · Belum Diklasifikasi (Not classified, `notClassified`) |
| Complaint urgency                | Rendah (Low, `low`) · Sedang (Medium, `medium`) · Tinggi (High, `high`) |
| Tenant account                   | Belum Diaktifkan (Not activated, `notActivated`) · Aktif (Active, `active`)                                                                                                                                           |
| Manager account                  | Belum Terkirim (Invitation not sent, `invitationNotSent`) · Belum Diaktivasi (Not activated, `notActivated`) · Aktif (Active, `active`)                                                                               |
| User account (Admin view)        | Aktif (Active, `active`) · Nonaktif (Inactive, `inactive`)                                                                                                                                                            |
| Subscription order / transaction | Menunggu Pembayaran (Awaiting payment, `awaitingPayment`) · Berhasil (Succeeded, `succeeded`) · Gagal (Failed, `failed`) · Kedaluwarsa (Expired, `expired`)                                                           |

Complaint status moves forward one step at a time: *Baru* → *Diproses* → *Selesai*. Nothing changes after *Selesai*.

Classification state is separate from status. *Menunggu Klasifikasi* = AI was attempted and failed or timed out. *Belum Diklasifikasi* = the Owner had no active subscription when the complaint was saved, so AI was skipped. A classified complaint has neither.

`new_` is only the Dart identifier, because `new` is reserved in Dart. The wire value is `"new"`.
<!-- shared:end -->

The allowed transitions are listed with the use case that causes them in §8.

## 6. Cross-cutting API rules

These apply to every use case below. Use cases do not repeat them.

1. **Session:** every endpoint except `GET /health` and the endpoints marked *public* in §9 requires a valid session, sent as an access token (§7). A missing, expired, revoked or invalid access token gets an authentication error with the code `ACCESS_TOKEN_INVALID`, which the app can tell apart from other errors and answers by refreshing the token.
2. **Errors** carry a stable error code, the field it belongs to (for validation errors), and an English message for developers and logs. The app shows Indonesian text mapped from the code, so validation errors can be shown next to their field. The codes are part of the OpenAPI document (response shape and code list: U-9).
3. **Conflict:** a write based on data another user has changed since it was read is rejected with a conflict error and not applied (detection: U-15).
4. **Failure is atomic:** a request that fails saves nothing, so the user can retry. The only partial outcomes are the ones a use case states (an invitation, a notification or an AI call failing after the main save).
5. **Empty lists** are a successful response with no items, not an error.
6. **Subscription gating:** the API decides whether the Owner of the property has an active subscription. Without one, gated content (AI classification, payment-pattern summary) is withheld, and the response says so. The rest of the response is unaffected.
7. **AI failure** (error or timeout) never blocks or rolls back saving data (policy: U-8).
8. **Soft delete** keeps history. Soft-deleted records are hidden from normal lists but kept for the history the use cases name.
9. **Transport:** HTTPS only (NFR-08).

## 7. Account access

*Shared with niscala-app.*

<!-- shared:begin -->
Login and sign-up are preconditions, not use cases. All use cases assume a valid session. The account identifier is **email**.

- **Owner** signs up and logs in with Google or a local password (FR-20).
- **Tenant** activates through an invitation link shared by management. During activation the tenant completes whatever data management left empty, including email and at least 2 emergency contacts if management gave none, then chooses Google or a local password (FR-01).
- **Manager** activates through an invitation sent to their email by the Owner, with Google or a local password (FR-26).
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
    - every session ends at most 30 days after the last authentication, regardless of activity (NIST SP 800-63B Rev. 3, AAL1);
    - a session ended by the user or by Admin stops working within 15 minutes at most.
<!-- shared:end -->

Additional backend rules:

- Rate limiting of failed logins MUST NOT use a puzzle-style CAPTCHA or a "retype the code" check. The API returns an error code the app shows in Indonesian.
- Deactivating or deleting an account ends its sessions (UC-30, UC-34, UC-35).
- **Password blocklist.** Checked on registration, on adding a password and on changing a password, after lowercasing. Reject if the password:
    - is in `data/common-passwords.txt` (top 100,000 from SecLists, MIT; loaded into a set at startup);
    - is one repeated character or an ascending/descending run (`aaaaaaaa`, `12345678`, `abcdefgh`);
    - contains "niscala", or the user's email local part or name (when ≥ 4 characters).

  The error code is `PASSWORD_TOO_COMMON`.
- **Sessions.** One `sessions` row per device, holding the hashed refresh token, device name, platform, login method, `last_active_at` and `revoked_at`. Revoking a session sets `revoked_at`. Access tokens live 15 minutes at most, so a revoked session stops working within 15 minutes. No IP address or location is stored.
- **Tokens.** The access token is a signed JWT valid for 15 minutes at most, sent as `Authorization: Bearer <token>`, and identifies the session. The refresh token is opaque, stored hashed on the `sessions` row, and rotated on every use: the old one stops working at once. Presenting an already-rotated or revoked refresh token ends that session. Refreshing never extends the 30-day cap. Sign-up, login, activation and refresh return both tokens in the JSON body.
- **Single-use links.** Invitation links last 7 days. Password-reset links last 30 minutes. Both can be used once. Creating a new invitation link or a new reset link invalidates the previous one.
- **Email.** Emails are trimmed and compared case-insensitively. An email belongs to one account.
- **Email verification** applies only to accounts with a local password (Owner sign-up, and Tenant or Manager activation with a password). Accounts created with Google count as verified. Verification uses a 6-digit code emailed to the account, valid 10 minutes, voided after 5 wrong attempts. A new code can be requested once every 60 seconds; requesting one voids the previous. Until the code is confirmed, the account can log in and use only the endpoints needed to verify the email, read its profile and log out; every other endpoint answers `EMAIL_NOT_VERIFIED`.
- **Google.** The app obtains a Google ID token and sends it; the backend verifies signature, audience and expiry and uses the token's `sub` as the identity. One Google identity belongs to one account. Google login finds the account by that identity, never by email (§7, "never links accounts automatically"). A Google-only account that is asked for a password reset receives nothing. Unlinking Google is not offered.
- **Login failures.** Failed local logins are counted per email address; after 5 failures the address is locked for 15 minutes and login answers `TOO_MANY_LOGIN_ATTEMPTS` with a `Retry-After` header, even for the right password. A successful login before the limit resets the count.
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

**UC-06 View notifications** (FR-08) · The Tenant's in-app notifications, newest first, with a read flag. Two types: due-date reminder (timing: U-12) and payment-status change. Each carries type, period and status. Opening one marks it read.

### 8.2 Management (Pemilik Kost and Pengelola Kost)

Lists are limited to the properties the caller may access: all of an Owner's own, or a Manager's assigned ones.

Every payment-status change (UC-05, UC-07, UC-08, UC-09) triggers regeneration of that Tenant's payment-pattern summary (UC-26). Changes made by management (UC-07, UC-08, UC-09) notify the Tenant (FR-08).

**UC-07 Verify or reject receipt** (FR-08, FR-09) · Lists payments *Menunggu Verifikasi*. Detail returns tenant, room, period, amount and the receipt image.
- Verify: *Menunggu Verifikasi* → *Lunas*. The payment date is the date the receipt was uploaded.
- Reject: requires a rejection reason; *Menunggu Verifikasi* → *Ditolak*. The Tenant may upload again (UC-05).

If notifying the Tenant fails, the status change still stands.

**UC-08 Record cash payment** (FR-08, FR-10) · Management only. For a bill that is *Belum Bayar* or *Ditolak*: takes the period and the date received (an invalid date, or a date after today, gets a field error) → *Lunas*, method *Tunai*.

**UC-09 Change payment status manually** (FR-08, FR-11) · Target status *Belum Bayar*, *Lunas* or *Ditolak*, with a **required** reason. Rejected with a field error if the target equals the current status or the reason is empty. When the target is *Lunas*, the method (*Tunai* or *Transfer*) and the date received are also required, with the same date rule as UC-08. For any other target they MUST be absent; otherwise a field error.

**UC-10 Add property** (FR-12, FR-21) · Owner only. Name and address required. The name MUST be unique within the Owner's account; a duplicate gets a field error. Optional bank account for rent transfers: bank name, account number, account holder name. If any bank-account field is given, all three are required.

**UC-11 View properties** (FR-12, FR-21) · Accessible properties, each with name, address, room count, occupied room count and assigned managers. Detail adds the vacant room count and the bank account, if set.

**UC-12 Edit property** (FR-12) · Owner only. Edits name, address and bank account.

**UC-13 Delete property** (FR-12) · Owner only. Rejected if the property has an active lease. On success the property's rooms and manager assignments are removed too.

**UC-14 Add room** (FR-12) · Fields:
- room number: required, MUST be unique within the property;
- base rate: required, per month, greater than 0;
- `lengthM` and `widthM`: optional, in metres, each 0 < x ≤ 20 with at most 2 decimals. Both or neither, otherwise a field error. Area is not stored;
- facilities: free-form tags. On save each tag is trimmed, lowercased and has repeated spaces collapsed; duplicates are dropped. At most 30 characters per tag and 15 tags per room (storage: U-19).

A suggestions endpoint returns the distinct facility tags already used on rooms of the same Owner.

**UC-15 View rooms** (FR-12) · Each room with number, base rate, occupancy, dimensions and facilities, plus, if occupied, the Tenant's name and the lease end date. Detail adds the Tenant's phone number, the lease start date and that lease's rent.

**UC-16 Edit room** (FR-12) · Same fields and rules as UC-14. Changing the base rate never changes the rent of existing leases.

**UC-17 Delete room** (FR-12) · Rejected if the room has an active lease.

**UC-18 Add tenant** (FR-13) · Required: a room that is *Kosong*, name, phone number. Optional: occupation, emergency contacts, lease dates, billing cycle (default monthly from the lease start date), grace period (default 0), rent.
- Phone number: MUST be an Indonesian mobile number: after removing spaces and dashes, `08` or `628` followed by 8 to 11 digits. Stored and returned as digits starting with `08`.
- Emergency contacts: 2 to 4, each with name, relationship and phone (same phone rule). Management may leave them empty while the account is *Belum Diaktifkan*; the Tenant then completes them during activation, which is rejected until there are 2 to 4 (§7). Exactly 1 contact is rejected with a field error.
- Rent: per billing cycle (the amount of one bill), greater than 0. If omitted on a monthly lease, it is set to the room's base rate; other cycles require it.
- Email is not set here; the Tenant fills it in during activation.

On save the room becomes *Terisi* and an invitation link is created and returned. If link creation fails, the Tenant is still saved and the link can be regenerated (UC-20).

**UC-19 View tenants** (FR-13) · Each Tenant with room number, name, account status, billing cycle and lease end date, plus the invitation expiry while the account is *Belum Diaktifkan*. Detail adds phone, email (once set), occupation, emergency contacts, the lease (dates, rent, billing cycle, grace period, next bill date) and, while the account is *Belum Diaktifkan*, the invitation: when it was created, when it expires, whether it has expired and, if not, its link.

**UC-20 Edit tenant** (FR-13) · Editable: name, phone, occupation, emergency contacts, lease dates, rent, billing cycle, grace period; the same rules as UC-18 apply, and an *Aktif* Tenant's emergency contacts cannot be emptied. The room cannot be changed here. Rejects a lease end date before the start date. A rent or billing-cycle change applies **from the next bill onward**.
Regenerate invitation link, for an unused or expired invitation (links last 7 days, §7): creates a new link and invalidates the old one. If regeneration fails, the old link stays valid. While an invitation is unused and not expired, its link can be shown again, so the backend keeps it in a form it can return (encrypted, not only hashed).

**UC-21 Delete tenant** (FR-13) · Soft delete: the lease ends, account access is revoked and the room becomes *Kosong*. Payment and complaint history is kept.

**UC-22 Occupancy dashboard** (FR-14) · Per property: occupied count, vacant count, occupancy percentage and each room's status, plus a summary across all accessible properties. All figures are computed here.

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

**UC-27 Add manager** (FR-22) · Name, email, and at least one property. Rejected if the email is already registered. An invitation is emailed. If sending fails, the account is saved as *Belum Terkirim* and the invitation can be resent (UC-29).

**UC-28 View managers** (FR-22) · Each Manager with name, email, assigned properties and account status.

**UC-29 Edit manager** (FR-22) · Changes name, email or assigned properties, keeping at least one property. Access to removed properties is revoked. Resend invitation: only for accounts that are not yet *Aktif*.

**UC-30 Delete manager** (FR-22) · Soft delete: assignments are revoked and active sessions end. The Manager's action history is kept.

**UC-31 Choose subscription plan** (FR-23, FR-25) · Returns the current subscription status and the available plans with features and price (plans and prices: U-11). With an active plan, also its end date. Confirming a plan creates an order *Menunggu Pembayaran*.

**UC-32 Pay for subscription** (FR-24, FR-25, FR-27) · Starts payment through the gateway (provider: TBD-3).
- *Berhasil* → the subscription is active;
- *Gagal* or *Kedaluwarsa* → the Owner may pay again;
- still pending → stays *Menunggu Pembayaran* and can be re-checked.

If the gateway is unreachable, return an error and create no transaction.

### 8.4 Admin

**UC-33 View user accounts** (FR-29) · All accounts with name, email, role and status. Search by email and filter by role; no match is an empty result.

**UC-34 Edit user account** (FR-29) · Changes name, email (MUST be unique) and status (*Aktif*/*Nonaktif*). Deactivating ends the account's sessions.

**UC-35 Delete user account** (FR-29) · Soft delete that ends sessions. Rejected, with an error code for the reason, if the account is an Owner with a property that has an active lease.

### 8.5 All roles

**UC-37 Manage active sessions** (FR-33, NFR-18) · Lists the caller's active sessions with device name, platform, login method and last activity, flagging the current one. The caller can end the session of one other device or of all other devices. The current session is not ended here; it ends through normal logout.

**UC-38 Change password** (FR-33, NFR-11) · Takes the current password and a new one; the new password is checked against the §7 rules. The response says whether the user has other sessions, so the app can offer to end them (UC-37).

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
- Authentication: an HTTP bearer scheme named `bearerAuth` (JWT access token) is declared on every operation except `GET /health` and the endpoints marked *public* below.
- Error responses (U-9) are not declared yet.

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

Every endpoint listed above except `GET /health` is declared in the contract but not implemented yet; it responds `501 Not Implemented`.

The response shape of `/health` is undecided (U-1).

## 10. Undecided — do not implement by assumption

When work touches one of these items, stop and raise it in Plan mode. Items that also affect the app are listed in its `docs/SPEC.md` §10 with the same ID.

| ID    | Item                                                                                                                             | Affects                   |
|-------|----------------------------------------------------------------------------------------------------------------------------------|---------------------------|
| TBD-3 | Payment gateway provider and its integration.                                                                                    | UC-32                     |
| U-1   | `/health` response shape.                                                                                                        | §9, NKMA-22               |
| U-4   | Invitation and password-reset link handling: how a link opens the app (Android App Links / deep link) and what happens if the app is not installed. | UC-18, UC-20, FR-01, NFR-11 |
| U-6   | Bill generation (FR-31): when bills are created, how the amount is set, and proration.                                           | UC-04, UC-08, UC-25       |
| U-8   | AI calls: timeout, retries, fallback, and whether classification runs within the save request or after it.                       | UC-02, UC-26              |
| U-9   | Error response shape and the list of error codes.                                                                                | §6, §7, all endpoints     |
| U-11  | Subscription plans, features and prices.                                                                                         | UC-31                     |
| U-12  | Due-date reminder timing.                                                                                                        | UC-06                     |
| U-15  | How conflicting writes are detected.                                                                                             | §6                        |
| U-16  | Complaint category list contents (the prototype list is placeholder data). Served by `GET /complaint-categories`, so the contract does not change when it is decided. | UC-02, UC-23, UC-36 |
| U-19  | Facility tag storage: `TEXT[]` column vs. join tables (proposed: `TEXT[]`).                                                      | UC-14, UC-16              |

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

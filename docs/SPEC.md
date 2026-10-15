# SPEC.md — Niscala backend

> **Audience:** coding agents working in this repository.
> **Scope:** the FastAPI backend only. The Flutter Android app lives in a separate repository (`andinaufal120/niscala-app`) and renders what this API returns.
> **Status:** self-contained. Everything an agent needs to know about required backend behaviour is in this file. Do not look for requirements elsewhere.

Traceability IDs (`FR-xx`, `NFR-xx`, `UC-xx`, `TBD-x`, `U-x`) are stable keys shared with the project's requirements baseline (v1.1, 11-10-2026), the app repository and Jira. Use them in commit messages and PR descriptions, never in source code or test names.

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
| Masa sewa (Lease)                                   | `Lease`                   | A tenant's occupancy of a room: start date, end date, billing cycle, grace period. |
| Penyewa (Tenant)                                    | `Tenant`                  | User who occupies a room; joins through an invitation link.                        |
| Pemilik Kost (Owner)                                | `Owner`                   | User who owns one or more properties and holds the subscription.                   |
| Pengelola Kost (Manager)                            | `Manager`                 | Optional user assigned by an Owner to specific properties.                         |
| Admin (Admin)                                       | `Admin`                   | Internal user who manages all user accounts.                                       |
| Manajemen kost (Management)                         | `management` (role group) | Owner and Manager together.                                                        |
| Undangan (Invitation)                               | `Invitation`              | Lets a Tenant or Manager activate an account.                                      |
| Laporan keluhan (Complaint)                         | `Complaint`               | Free-text maintenance report from a Tenant.                                        |
| Klasifikasi AI (AI classification)                  | `ComplaintClassification` | Category, urgency and suggested action for a complaint.                            |
| Tagihan sewa (Rent bill)                            | `RentBill`                | Rent owed for one billing period. Generated by the backend (FR-31).                |
| Pembayaran (Payment)                                | `Payment`                 | The payment record attached to a rent bill.                                        |
| Siklus penagihan (Billing cycle)                    | `BillingCycle`            | Weekly, monthly, 3, 6 or 12 months. Default: monthly from the lease start date.    |
| Masa tenggang (Grace period)                        | `gracePeriodDays`         | Days after the bill date before a payment is late. Default: 0.                     |
| Jatuh tempo (Due date)                              | `dueDate`                 | Bill date + grace period. Computed by the backend.                                 |
| Ringkasan pola pembayaran (Payment-pattern summary) | `PaymentPatternSummary`   | AI-written sentence built from rule-computed payment facts.                        |
| Langganan (Subscription)                            | `Subscription`            | The Owner's paid plan that unlocks AI features.                                    |
| Soft delete (Soft delete)                           | —                         | Marked inactive; history is kept.                                                  |
<!-- shared:end -->

The code names above are used in PEP 8 form in this repository (see `CLAUDE.md`, "Vocabulary"). Their values on the wire are undecided (U-10).

## 4. Roles and permissions

*Shared with niscala-app.*

<!-- shared:begin -->
`✓` allowed · `A` only on properties assigned to the Manager · `—` not allowed

| Capability                                                   | Tenant | Owner | Manager | Admin |
|--------------------------------------------------------------|:------:|:-----:|:-------:|:-----:|
| View own room, lease, payments, complaints, notifications    |   ✓   |   —   |    —    |   —   |
| Submit complaint, upload transfer receipt                    |   ✓   |   —   |    —    |   —   |
| Add / delete property                                        |   —    |  ✓   |    —    |   —   |
| View / edit property                                         |   —    |  ✓   |    A    |   —   |
| Add / view / edit / delete room                              |   —    |  ✓   |    A    |   —   |
| Add / view / edit / delete tenant                            |   —    |  ✓   |    A    |   —   |
| Verify/reject receipts, record cash, change payment status   |   —    |  ✓   |    A    |   —   |
| Occupancy dashboard, complaint list, change complaint status |   —    |  ✓   |    A    |   —   |
| Payment status of all tenants, payment-pattern view          |   —    |  ✓   |    A    |   —   |
| Add / view / edit / delete managers                          |   —    |  ✓   |    —    |   —   |
| Choose and pay for a subscription                            |   —    |  ✓   |    —    |   —   |
| View / edit / delete any user account                        |   —    |   —   |    —    |  ✓   |

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
| Complaint                        | Baru (New, `new_`) · Menunggu Klasifikasi (Awaiting classification, `awaitingClassification`) · Belum Diklasifikasi (Not classified, `notClassified`) · Diproses (In progress, `inProgress`) · Selesai (Done, `done`) |
| Tenant account                   | Belum Diaktifkan (Not activated, `notActivated`) · Aktif (Active, `active`)                                                                                                                                           |
| Manager account                  | Belum Terkirim (Invitation not sent, `invitationNotSent`) · Belum Diaktivasi (Not activated, `notActivated`) · Aktif (Active, `active`)                                                                               |
| User account (Admin view)        | Aktif (Active, `active`) · Nonaktif (Inactive, `inactive`)                                                                                                                                                            |
| Subscription order / transaction | Menunggu Pembayaran (Awaiting payment, `awaitingPayment`) · Berhasil (Succeeded, `succeeded`) · Gagal (Failed, `failed`) · Kedaluwarsa (Expired, `expired`)                                                           |

Complaint meaning: *Menunggu Klasifikasi* = AI was attempted and failed or timed out. *Belum Diklasifikasi* = the Owner had no active subscription when the complaint was saved, so AI was skipped.
<!-- shared:end -->

The allowed transitions are listed with the use case that causes them in §8.

## 6. Cross-cutting API rules

These apply to every use case below. Use cases do not repeat them.

1. **Session:** every endpoint except `GET /health` requires a valid session. An expired or invalid session gets an authentication error the app can tell apart from other errors (mechanism: U-14).
2. **Validation errors** name the field and the cause, so the app can show the cause next to the field (shape and language: U-9).
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
- **Tenant** activates through an invitation link shared by management. During activation the tenant completes whatever data management left empty, including email, then chooses Google or a local password (FR-01).
- **Manager** activates through an invitation sent to their email by the Owner, with Google or a local password (FR-26).
- **Profile menu (FR-30):** a Google-only user can add a local password. A password user can link Google, but only after logging in with the password. The app never links accounts automatically by matching email.
- **Local password rules (NFR-11, NIST SP 800-63B Rev. 3, AAL1).** These apply only to accounts with a local password:
    - minimum 8 characters, and at least 64 accepted;
    - no composition rules and no forced periodic change;
    - a show-password toggle while typing;
    - the backend checks passwords against common/breached lists and rate-limits failed logins. The app shows those errors as returned.
<!-- shared:end -->

Additional backend rules:

- Rate limiting of failed logins MUST NOT use a puzzle-style CAPTCHA or a "retype the code" check. The API returns a message the app can show as is.
- Deactivating or deleting an account ends its sessions (UC-30, UC-34, UC-35).

## 8. Server-side rules per use case

Same IDs and order as the app's use cases. Only what the backend must enforce or return is listed. Permissions follow §4; "management" means Owner, or Manager on an assigned property.

### 8.1 Tenant (Penyewa)

**UC-01 View room and lease** (FR-02) · Returns the Tenant's room number, facilities, and lease start and end dates, or a result the app can recognise as "no room or lease".

**UC-02 Submit maintenance complaint** (FR-03, FR-04, FR-25, FR-28) · Tenant with an active lease only. Rejects an empty or too-short description with a field error (minimum length: U-3). Saving the complaint MUST NOT depend on the AI result. After saving, the complaint is *Baru* and carries exactly one of:
- a classification (category, urgency, suggested action);
- *Menunggu Klasifikasi*: the AI was attempted and failed or timed out;
- *Belum Diklasifikasi*: the Owner had no active subscription when the complaint was saved, so the AI was skipped.

**UC-03 View complaint status and history** (FR-05) · The Tenant's own complaints with status. Detail includes category and urgency when classified.

**UC-04 View rent payment history and status** (FR-06) · Tenant with an active lease. Bills and payments with status, period, amount and due date (bill date + grace period).

**UC-05 Upload transfer receipt** (FR-07) · Allowed only for the Tenant's current-period payment that is *Belum Bayar* or *Ditolak*. Rejects an invalid format or size with a field error (limits: U-2). On success: *Menunggu Verifikasi*.

**UC-06 View notifications** (FR-08) · The Tenant's in-app notifications, newest first, with a read flag. Two types: due-date reminder (timing: U-12) and payment-status change. Each carries type, period and status. Opening one marks it read.

### 8.2 Management (Pemilik Kost and Pengelola Kost)

Lists are limited to the properties the caller may access: all of an Owner's own, or a Manager's assigned ones.

Every payment-status change (UC-05, UC-07, UC-08, UC-09) triggers regeneration of that Tenant's payment-pattern summary (UC-26). Changes made by management (UC-07, UC-08, UC-09) notify the Tenant (FR-08).

**UC-07 Verify or reject receipt** (FR-08, FR-09) · Lists payments *Menunggu Verifikasi*. Detail returns tenant, room, period, amount and the receipt image.
- Verify: *Menunggu Verifikasi* → *Lunas*.
- Reject: requires a rejection reason; *Menunggu Verifikasi* → *Ditolak*. The Tenant may upload again (UC-05).

If notifying the Tenant fails, the status change still stands.

**UC-08 Record cash payment** (FR-08, FR-10) · Management only. For a bill that is *Belum Bayar* or *Ditolak*: takes the period and the date received (an invalid date gets a field error) → *Lunas*, method *Tunai*.

**UC-09 Change payment status manually** (FR-08, FR-11) · Target status *Belum Bayar*, *Lunas* or *Ditolak*, with a **required** reason. Rejected with a field error if the target equals the current status or the reason is empty.

**UC-10 Add property** (FR-12, FR-21) · Owner only. Name and address required. The name MUST be unique within the Owner's account; a duplicate gets a field error.

**UC-11 View properties** (FR-12, FR-21) · Accessible properties, each with room count and assigned managers.

**UC-12 Edit property** (FR-12) · Edits name and address.

**UC-13 Delete property** (FR-12) · Owner only. Rejected if the property has an active lease. On success the property's rooms and manager assignments are removed too.

**UC-14 Add room** (FR-12) · Room number, rent rate, facilities. The room number MUST be unique within the property.

**UC-15 View rooms** (FR-12) · Each room with number, rate and occupancy. Detail adds facilities, plus the Tenant and lease if occupied.

**UC-16 Edit room** (FR-12) · Same fields and rules as UC-14.

**UC-17 Delete room** (FR-12) · Rejected if the room has an active lease.

**UC-18 Add tenant** (FR-13) · Required: a room that is *Kosong*, name, phone number. Optional: other personal data, lease dates, billing cycle (default monthly from the lease start date), grace period (default 0). On save the room becomes *Terisi* and an invitation link is created and returned. If link creation fails, the Tenant is still saved and the link can be regenerated (UC-20).

**UC-19 View tenants** (FR-13) · Each Tenant with room, lease and account status. Detail adds personal data and activation status.

**UC-20 Edit tenant** (FR-13) · Editable: name, phone, other data, lease dates, billing cycle, grace period. Rejects a lease end date before the start date. A billing-cycle change applies **from the next bill onward**.
Regenerate invitation link, for an unused or expired invitation (expiry: U-13): creates a new link and invalidates the old one. If regeneration fails, the old link stays valid.

**UC-21 Delete tenant** (FR-13) · Soft delete: the lease ends, account access is revoked and the room becomes *Kosong*. Payment and complaint history is kept.

**UC-22 Occupancy dashboard** (FR-14) · Per property: occupied count, vacant count, occupancy percentage and each room's status, plus a summary across all accessible properties. All figures are computed here.

**UC-23 Complaint list with AI classification** (FR-15, FR-25) · Complaints across accessible properties, sorted by urgency, then time. Includes category, urgency and suggested action when available; otherwise the complaint status. Without an active subscription, classification results are withheld (§6 rule 6).

**UC-24 Change complaint status** (FR-16) · Target *Diproses* or *Selesai*, with an optional handling note. Rejected once the complaint is *Selesai*.

**UC-25 Payment status of all tenants** (FR-17) · For a property and a period (default: current): each Tenant with room, amount and payment status, and each Tenant's payment history.

**UC-26 Payment-pattern summary** (FR-18, FR-19, FR-25, FR-28) · For every Tenant:
- rule-computed facts, e.g. average days paid relative to the due date, and late frequency (formulas: U-7);
- an at-risk flag (threshold: U-7);
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

**UC-35 Delete user account** (FR-29) · Soft delete that ends sessions. Rejected, with the reason returned, if the account is an Owner with a property that has an active lease.

## 9. API contract

This repository owns the contract. The OpenAPI document FastAPI generates from the code is the source; the app generates a Dart client from it and never hand-edits it. A breaking change (removed or renamed path, field or enum value, changed type) is released together with an app PR.

The only endpoint so far:

| Method | Path      | Purpose                                                   | Used by                                                   |
|--------|-----------|-----------------------------------------------------------|-----------------------------------------------------------|
| `GET`  | `/health` | Confirms the API is up and its database connection works. | Walking skeleton (NKMA-6): the app displays the response. |

The response shape of `/health` is undecided (U-1).

## 10. Undecided — do not implement by assumption

When work touches one of these items, stop and raise it in Plan mode. Items that also affect the app are listed in its `docs/SPEC.md` §10 with the same ID.

| ID    | Item                                                                                                                             | Affects                   |
|-------|----------------------------------------------------------------------------------------------------------------------------------|---------------------------|
| TBD-3 | Payment gateway provider and its integration.                                                                                    | UC-32                     |
| U-1   | `/health` response shape.                                                                                                        | §9, NKMA-22               |
| U-2   | Receipt upload: allowed file formats and maximum size.                                                                           | UC-05                     |
| U-3   | Complaint description minimum length.                                                                                            | UC-02                     |
| U-4   | Invitation link handling: how a link opens the app (Android App Links / deep link) and what happens if the app is not installed. | UC-18, UC-20, FR-01       |
| U-6   | Bill generation (FR-31): when bills are created, how the amount is set, and proration.                                           | UC-04, UC-08, UC-25       |
| U-7   | Payment-pattern facts: formulas, and the at-risk threshold.                                                                      | UC-26                     |
| U-8   | AI calls: timeout, retries, fallback, and whether classification runs within the save request or after it.                       | UC-02, UC-26              |
| U-9   | User-facing API messages: language (the app UI is Indonesian and shows some errors as returned) and whether errors carry codes.  | §6, §7, all field errors  |
| U-10  | Wire formats: enum values, JSON field casing, and date/time format.                                                              | §3, §5, §9, all endpoints |
| U-11  | Subscription plans, features and prices.                                                                                         | UC-31                     |
| U-12  | Due-date reminder timing.                                                                                                        | UC-06                     |
| U-13  | Invitation expiry.                                                                                                               | UC-18, UC-20, UC-27       |
| U-14  | Authentication mechanism and session lifetime.                                                                                   | §6, §7                    |
| U-15  | How conflicting writes are detected.                                                                                             | §6                        |

## 11. Changelog

| Date       | Change                                                                                                                    | Decided in |
|------------|---------------------------------------------------------------------------------------------------------------------------|------------|
| 15-10-2026 | Initial version, derived from the app's `docs/SPEC.md` and requirements baseline v1.1 (11-10-2026). Shared blocks marked. | NKMA-14    |

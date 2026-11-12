# Traceability: use cases to tests

Which tests exercise each use case of `docs/SPEC.md`. For agents and reviewers.

Test names and docstrings carry no use case IDs (`CLAUDE.md`), so the link is by topic: each row names the end-to-end scenario files (`tests/e2e/`) that tell the use case as a story through the public API, and the endpoint, service and contract test files (`tests/`) that cover its rules one by one. A use case with several files is covered from several sides; the files of one row are not all about that use case alone.

Keep it current: when a use case or a test file is added or renamed, update its row in the same change. Left out on purpose: tests of infrastructure (command line, database, migrations, settings, logging, health), the end-to-end harness (`tests/e2e/test_harness.py`, `tests/e2e/test_rent_steps.py`) and the shared fixtures in `tests/conftest.py`.

## Use cases

| Use case | End-to-end scenarios (`tests/e2e/`) | Endpoint, service and contract tests (`tests/`) |
|----------|-------------------------------------|------------------------------------------------|
| UC-01 View room and lease | `test_tenancy_journeys`, `test_invitation_journeys` | `test_my_lease`, `test_lease_contract`, `test_lease_service` |
| UC-02 Submit maintenance complaint | `test_complaint_journeys`, `test_complaint_ai_journeys` | `test_complaint_submission`, `test_complaint_photo`, `test_complaint_photo_model`, `test_complaint_classification`, `test_gemini_complaint_flow`, `test_complaint_contract` |
| UC-03 View complaint status and history | `test_complaint_journeys` | `test_complaint_reading`, `test_complaint_status_change`, `test_complaint_contract` |
| UC-04 View rent payment history and status | `test_payment_journeys`, `test_bill_journeys` | `test_rent_bill_reads`, `test_rent_bill_contract`, `test_rent_bill_models` |
| UC-05 Upload transfer receipt | `test_payment_journeys` | `test_rent_bill_receipt_upload`, `test_storage` |
| UC-06 View notifications | `test_payment_journeys`, `test_bill_journeys`, `test_complaint_journeys`, `test_complaint_ai_journeys`, `test_invitation_journeys` | `test_notification_reading`, `test_notification_settings`, `test_notification_creation_accounts`, `test_notification_creation_complaints`, `test_notification_creation_payments`, `test_notification_bill_reminders`, `test_notification_push`, `test_notification_contract`, `test_push_token`, `test_push_sender` |
| UC-07 Verify or reject receipt | `test_payment_journeys` | `test_rent_bill_review` |
| UC-08 Record cash payment | `test_payment_journeys` | `test_rent_bill_payments` |
| UC-09 Change payment status manually | `test_payment_journeys` | `test_rent_bill_payments` |
| UC-10 Add property | `test_property_journeys` | `test_property_endpoints`, `test_property_contract`, `test_property_models`, `test_property_access` |
| UC-11 View properties | `test_property_journeys` | `test_property_endpoints`, `test_property_contract`, `test_property_access` |
| UC-12 Edit property | `test_property_journeys`, `test_sessions_and_passwords` | `test_property_endpoints`, `test_require_recent_reauthentication`, `test_password_reauthentication`, `test_google_reauthentication`, `test_reauthentication_contract` |
| UC-13 Delete property | `test_property_journeys` | `test_property_endpoints` |
| UC-14 Add room | `test_room_journeys`, `test_downgrade_journeys` | `test_room_endpoints`, `test_room_models`, `test_room_contract`, `test_subscription_plan_limits` |
| UC-15 View rooms | `test_room_journeys` | `test_room_endpoints`, `test_room_occupancy`, `test_room_contract` |
| UC-16 Edit room | `test_room_journeys`, `test_downgrade_journeys` | `test_room_endpoints`, `test_room_contract` |
| UC-17 Delete room | `test_room_journeys`, `test_downgrade_journeys` | `test_room_endpoints` |
| UC-18 Add tenant | `test_tenancy_journeys`, `test_invitation_journeys` | `test_tenant_endpoints`, `test_tenant_contract`, `test_tenant_models`, `test_invitation_service`, `test_invitation_preview`, `test_invitation_activation`, `test_google_invitation_activation` |
| UC-19 View tenants | `test_tenancy_journeys` | `test_tenant_endpoints`, `test_lease_service`, `test_tenant_contract` |
| UC-20 Edit tenant | `test_tenancy_journeys`, `test_invitation_journeys` | `test_tenant_endpoints`, `test_invitation_service` |
| UC-21 Delete tenant | `test_tenancy_journeys` | `test_tenant_endpoints`, `test_tenant_invitation_acceptance` |
| UC-22 Occupancy dashboard | `test_room_journeys` | `test_occupancy_dashboard`, `test_occupancy_dashboard_contract` |
| UC-23 Complaint list with AI classification | `test_complaint_ai_journeys`, `test_subscription_journeys` | `test_complaint_reading`, `test_complaint_classification`, `test_complaint_classifier`, `test_gemini_classifier`, `test_gemini_complaint_flow` |
| UC-24 Change complaint status | `test_complaint_journeys` | `test_complaint_status_change` |
| UC-25 Payment status of all tenants | `test_payment_journeys` | `test_payment_overview` |
| UC-26 Payment-pattern summary | `test_payment_pattern_journeys` | `test_payment_facts`, `test_payment_patterns`, `test_payment_pattern_summarizer`, `test_payment_pattern_summary_generation`, `test_payment_pattern_summary_model`, `test_payment_pattern_summary_reading`, `test_gemini_payment_summarizer`, `test_payment_pattern_contract` |
| UC-27 Add manager | `test_manager_journeys`, `test_invitation_journeys` | `test_manager_endpoints`, `test_manager_contract`, `test_manager_models`, `test_manager_invitation_preview`, `test_manager_invitation_activation` |
| UC-28 View managers | `test_manager_journeys` | `test_manager_endpoints`, `test_manager_contract` |
| UC-29 Edit manager | `test_manager_journeys`, `test_invitation_journeys` | `test_manager_changes`, `test_manager_endpoints` |
| UC-30 Delete manager | `test_manager_journeys` | `test_manager_changes`, `test_manager_endpoints`, `test_user_account_deletion` |
| UC-31 Choose subscription plan | `test_subscription_journeys`, `test_downgrade_journeys` | `test_subscription_endpoints`, `test_subscription_downgrade`, `test_subscription_service`, `test_subscription_stale_confirmation`, `test_plans`, `test_subscription_plan_limits`, `test_subscription_contract`, `test_subscription_model` |
| UC-32 Pay for subscription | `test_subscription_journeys` | `test_subscription_purchase_verification`, `test_subscription_order_models`, `test_google_play_client`, `test_google_play_notifications`, `test_google_play_reconcile`, `test_google_play_sync` |
| UC-33 View user accounts | `test_admin_journeys` | `test_user_account_listing`, `test_user_account_reading`, `test_user_account_contract`, `test_user_account_access` |
| UC-34 Edit user account | `test_admin_journeys`, `test_sessions_and_passwords` | `test_user_account_changes`, `test_email_change_confirmation`, `test_email_change_sender`, `test_account_status_login` |
| UC-35 Delete user account | `test_admin_journeys` | `test_user_account_deletion`, `test_account_status_login` |
| UC-36 Classify complaint manually | `test_complaint_ai_journeys` | `test_complaint_manual_classification`, `test_complaint_contract` |
| UC-37 Manage active sessions | `test_sessions_and_passwords` | `test_my_sessions`, `test_session_endpoints`, `test_session_contract`, `test_session_models`, `test_end_expired_sessions`, `test_start_session` |
| UC-38 Change password | `test_sessions_and_passwords` | `test_change_password`, `test_password_rules`, `test_passwords` |

## Beyond the use cases

| Behavior | End-to-end scenarios (`tests/e2e/`) | Tests (`tests/`) |
|----------|-------------------------------------|------------------|
| Account access: sign-up, login, activation, Google, password reset, email verification | `test_sessions_and_passwords`, `test_invitation_journeys` | `test_register_endpoint`, `test_register_password_rules`, `test_login_endpoint`, `test_login_rate_limit`, `test_login_failure_model`, `test_email_verification_endpoints`, `test_email_verification_models`, `test_google_login`, `test_google_register`, `test_google_linking`, `test_local_password_addition`, `test_password_reset_request`, `test_password_reset_preview`, `test_password_reset_completion`, `test_invitation_acceptance`, `test_verified_user`, `test_current_user`, `test_require_roles`, `test_user_account_access`, `test_account_access_contract`, `test_google_verifier`, `test_google_identity_model`, `test_email_sender`, `test_password_reset_sender` |
| Bill generation by the daily job | `test_bill_journeys` | `test_bill_generation`, `test_bill_generation_notifications`, `test_daily_jobs`, `test_notification_bill_reminders` |
| Error codes and their declaration in the OpenAPI document | - | `test_error_catalog`, `test_openapi_errors`, `test_declared_errors_match_responses`, `test_error_response`, `test_openapi_info` |
| Record versions and If-Match | `test_property_journeys`, `test_room_journeys`, `test_manager_journeys`, `test_admin_journeys` | `test_resource_versions`, `test_if_match` |
| Android App Links: assetlinks file and link pages | - | `test_app_links_settings`, `test_assetlinks`, `test_link_pages` |

## Alternative flows

| Flow | End-to-end scenarios (`tests/e2e/`) |
|------|-------------------------------------|
| AI unavailable or timing out | `test_complaint_ai_journeys`, `test_payment_pattern_journeys` |
| Subscription inactive or lapsed | `test_subscription_journeys`, `test_complaint_ai_journeys`, `test_downgrade_journeys` |
| Concurrent edits of the same record | `test_property_journeys`, `test_room_journeys`, `test_manager_journeys`, `test_admin_journeys` |

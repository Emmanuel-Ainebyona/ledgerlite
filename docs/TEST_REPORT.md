# Test report (authoring environment)

Command: `python -m unittest discover -s tests -t . -v`  
Environment: Python 3.12.3, Flask 3.1.3, SQLite 3.45.1

Overall: Ran 37 tests in 11.975s OK

| Test | Result |
|---|---|
| `test_core.AuthTests.test_bad_credentials_are_indistinguishable` | PASS |
| `test_core.AuthTests.test_duplicate_email_case_insensitive` | PASS |
| `test_core.AuthTests.test_health` | PASS |
| `test_core.AuthTests.test_logout_revokes_token` | PASS |
| `test_core.AuthTests.test_protected_requires_valid_token` | PASS |
| `test_core.AuthTests.test_rate_limit_on_login` | PASS |
| `test_core.AuthTests.test_register_login_me` | PASS |
| `test_core.AuthTests.test_register_validation` | PASS |
| `test_core.HardeningTests.test_cors_allowlist` | PASS |
| `test_core.HardeningTests.test_errors_are_json_and_do_not_leak` | PASS |
| `test_core.HardeningTests.test_pagination_and_bad_params` | PASS |
| `test_core.HardeningTests.test_passwords_stored_hashed` | PASS |
| `test_core.HardeningTests.test_production_requires_strong_secret` | PASS |
| `test_core.HardeningTests.test_security_headers` | PASS |
| `test_core.HardeningTests.test_sql_injection_attempts_are_inert` | PASS |
| `test_core.HardeningTests.test_static_frontend_and_path_traversal` | PASS |
| `test_core.UserAdminTests.test_admin_cannot_demote_or_disable_self` | PASS |
| `test_core.UserAdminTests.test_audit_log_records_events_and_hides_secrets` | PASS |
| `test_core.UserAdminTests.test_deactivated_user_loses_access_and_login` | PASS |
| `test_core.UserAdminTests.test_non_admin_forbidden` | PASS |
| `test_core.UserAdminTests.test_reset_password` | PASS |
| `test_core.UserAdminTests.test_role_change_applies_immediately_and_validates` | PASS |
| `test_domain.AccountTests.test_crud_rbac_validation` | PASS |
| `test_domain.AccountTests.test_system_and_posted_accounts_protected` | PASS |
| `test_domain.InvariantTests.test_books_balance_and_ar_matches_open_invoices` | PASS |
| `test_domain.InvariantTests.test_income_statement_and_stats` | PASS |
| `test_domain.InvoiceTests.test_concurrent_payments_cannot_overpay` | PASS |
| `test_domain.InvoiceTests.test_customer_with_invoices_cannot_be_deleted` | PASS |
| `test_domain.InvoiceTests.test_invoice_posts_to_ledger` | PASS |
| `test_domain.InvoiceTests.test_invoice_validation_and_rbac` | PASS |
| `test_domain.InvoiceTests.test_payments_partial_full_overpay` | PASS |
| `test_domain.InvoiceTests.test_void_rules` | PASS |
| `test_domain.JournalTests.test_balanced_entry_posts_and_trial_balance_stays_balanced` | PASS |
| `test_domain.JournalTests.test_database_enforces_immutability` | PASS |
| `test_domain.JournalTests.test_invalid_entries_rejected_and_nothing_posted` | PASS |
| `test_domain.JournalTests.test_rbac` | PASS |
| `test_domain.JournalTests.test_reversal_nets_to_zero_and_only_once` | PASS |

Failures found and fixed during development are listed in the delivery notes; nothing here is marked PASS without having been executed.

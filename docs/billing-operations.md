# Billing operations (B5)

All records remain in the billing app and existing PostgreSQL database. This provides invoice-ready records and external accounting exports; it is not a general ledger, tax filing integration or real payment gateway.

## Permissions and operational entry points

After applying migrations, run `python manage.py configure_billing_roles` to create/update the managed groups below. This command assigns no users and grants no simulator access. Enroll appropriate active staff explicitly using Django's existing user/group administration. Rerunning the command resets these managed groups to their documented permission sets.

| Managed group | Authority |
|---|---|
| Billing financial viewer | Read financial records, documents, settlements and audit evidence |
| Billing plan manager | Create/edit plans and entitlements with an audit reason; no deletion |
| Billing refund approver | Read finances and approve full-order refunds |
| Billing Premium granter | Manually activate/renew Premium through the lifecycle form; no payment/refund authority |
| Billing finance operator | Read finances, issue invoice/credit-note records, record settlements/reconciliation and export CSVs |
| Billing configuration reviewer | Read finances and review seller, tax and retention configuration |

Existing model-specific view permissions still allow scoped inspection. `manage_subscriptions` remains the trusted payment processor/expiration/revocation permission; it alone no longer authorizes manual grants or refund approvals. Existing staff must receive the appropriate new permissions/groups. Superusers retain explicit administrative authority. The simulator still separately requires its B4 environment guards and simulator permission.

The Admin **Financial audit events** changelist links to permission-filtered financial operations and CSV exports. The **User subscriptions** changelist links to the existing lifecycle form, now filtered to authorized operations. Financial records themselves remain read-only; plan and configuration forms require an audit reason. All custom mutations/downloads use CSRF-protected POSTs. Grants remain in immutable SubscriptionEvent history; finance operations, plan/configuration edits, processed payment events and completed exports append FinancialAuditEvent rows with actor/time/reason/references and relevant before/after data.

## Refunds and corrections

Approve a full refund against a paid order using the financial operations form. Approval preserves the original approver and reason. Approval alone moves no money and revokes no access. In an explicitly enabled test environment a separately authorized simulator operator confirms the full-refund event. Confirmation creates the Refund, preserves the successful payment, revokes its associated Premium term through B3, and retains the approver. A simulator operator can auto-approve only with the separate approve_refunds permission. Paid subscriptions cannot bypass this workflow through the older subscription-only refund form.

Correct statement observations by appending a reconciliation record; never replace the original evidence. Correct a fully refunded sale by issuing a credit note referring to its original invoice. Arbitrary edits to finalized orders, successful/failed payments, refunds, documents or audit rows are unsupported. No partial refunds, document amendments or arbitrary balance adjustments are implemented.

## Seller, tax and invoice-ready records

Before launch, a configuration reviewer must explicitly set and review seller name/address, declared tax registration status/number, tax treatment and components. No GST registration, rate, exemption or customer location is inferred. `unconfigured` blocks invoice issuance. `none` is an explicit reviewed no-tax choice. `inclusive` divides the immutable gross order amount into net and the configured named percentage components; it requires declared registration and positive configured rates. It never changes the collected amount. Unsupported treatments require future implementation and review; these records do not claim statutory invoice compliance.

Issuance is a controlled office workflow after payment confirmation. No invoices or historical tax amounts are fabricated for earlier purchases. Sales with no issued document export blank invoice/tax fields. Changing configuration clears review unless the reviewer explicitly reviews again. Issued documents freeze seller details, customer account/order reference, plan snapshot, INR total/net/tax, named tax breakdown and issue date. Review and validate these settings and the resulting records for the business before any future real-provider launch.

Numbering uses locked per-kind/per-year sequences and configurable distinct prefixes, for example `INV/2026-27/000001`. Financial years run April–March; issue dates and export date bounds use Asia/Kolkata. Numbers are unique; retries and simultaneous issue requests do not duplicate documents. Issuance date is the actual current date, not a silently backdated payment date. A full-refund credit note uses the original invoice's exact seller, net, tax components and total even when current configuration differs; it receives its own number and current financial year.

## Reconciliation and exports

Record observed settlement reference/provider, gross, gateway fee, fee tax, net and aware settlement timestamp. Fees are supplied from evidence, never assumed. Net must equal gross minus fee and fee tax. Settlement records are immutable; payment reconciliation can associate many payments with a settlement of the same provider/currency. This association does not invent allocations or automatically prove batch completeness.

Payments and settlements default to unreconciled. Each new statement observation records actor, reason, reference, expected and observed amount, and matched/mismatch status. Reopening uses an appended unreconciled observation. Latest status appears on payment/settlement Admin lists; all earlier observations remain visible. A matched observation must have equal expected and observed amounts. Payment observations use original successful gross payment, settlement observations use net bank settlement; refunds reconcile separately in their export.

CSV exports require both view_financial_records and export_financial_records, plus a reason. Optional date bounds are inclusive local dates. Each completed export audits report, filters, row count and SHA-256 of the UTF-8 CSV. Text cells are guarded against spreadsheet formula injection; financial numeric cells remain numeric. Reports use stable order/payment/refund/settlement/document references and account IDs, not account emails or banking data.

- Sales: original confirmed sales (including later refunded orders), quote/amount, invoice/FY/date, net/tax/breakdown and seller snapshot when issued. Sale date is subscription allocation creation/confirmation, including queued renewals.
- Payments: payment reference/status/amount, processing timestamp, latest reconciliation and optional settlement reference.
- Refunds: full original amount, payment/order reference, approver and credit-note reference where issued.
- Settlements: observed gross, gateway fee, fee tax, net, reference and reconciliation. No rows are fabricated if no settlement evidence exists.
- Tax summary: issued invoices minus issued credit notes, grouped by document financial year, currency and configured component/rate. Components may share a taxable base; do not sum repeated bases across components. Unissued documents are absent, not treated as zero tax. Reconcile refunds missing credit-note references before using a tax summary externally.

Sales and refunds are separate accounting facts; do not treat a refunded sale's original gross as an additional net receipt. Use their stable references to import/reconcile them in external accounting software. No GST filing endpoint or external connector is configured.

## Retention and integrity

Configuration supports financial/audit retention days (blank = indefinite) and a legal hold. `retention_review` reports when a record is eligible for a human archival/retention review; it never authorizes deletion. Unconfigured policy, indefinite retention or legal hold prevents eligibility. B5 provides no automated purge or erasure service, so even expired retention periods cannot silently remove financial history.

Protected relationships and ORM guards prevent unauthorized deletion. PostgreSQL migration 0009 also rejects UPDATE/DELETE of immutable documents, approvals, refunds, settlements, reconciliation evidence and audit events; it permits only valid order/payment/event processing transitions, immutable managed subscription terms, monotonic document counters and configuration updates. Test database TRUNCATE remains available to Django's test runner. Reversing this migration explicitly removes its guards; reversing schema migrations can remove tables, so use normal controlled migration/backup procedures.

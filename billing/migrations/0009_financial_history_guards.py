from django.db import migrations


TABLES = (
    "billing_paymentorder", "billing_paymenttransaction", "billing_paymentevent", "billing_refund",
    "billing_financialauditevent", "billing_refundapproval", "billing_billingdocument",
    "billing_settlement", "billing_reconciliationrecord", "billing_documentsequence",
    "billing_billingconfiguration", "billing_subscriptionevent", "billing_usersubscription",
)

FUNCTION = """
CREATE FUNCTION billing_guard_financial_history() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE previous jsonb; incoming jsonb;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Billing history must be retained' USING ERRCODE = '23514';
    END IF;
    previous := to_jsonb(OLD);
    incoming := to_jsonb(NEW);
    IF TG_TABLE_NAME = 'billing_paymentorder' THEN
        IF previous - ARRAY['status','subscription_id'] <> incoming - ARRAY['status','subscription_id']
            OR (OLD.subscription_id IS NOT NULL AND OLD.subscription_id IS DISTINCT FROM NEW.subscription_id)
            OR NOT (OLD.status = NEW.status OR (OLD.status IN ('created','pending') AND NEW.status IN ('pending','failed','paid'))
                    OR (OLD.status = 'paid' AND NEW.status = 'refunded')) THEN
            RAISE EXCEPTION 'Invalid order mutation' USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'billing_paymenttransaction' THEN
        IF previous - 'status' <> incoming - 'status'
            OR NOT (OLD.status = NEW.status OR (OLD.status = 'pending' AND NEW.status IN ('failed','success'))) THEN
            RAISE EXCEPTION 'Finalized payments are immutable' USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'billing_paymentevent' THEN
        IF previous - ARRAY['result','processed_at'] <> incoming - ARRAY['result','processed_at']
            OR (OLD.result <> 'received' AND previous <> incoming)
            OR (OLD.result = 'received' AND NEW.result NOT IN ('processed','ignored')) THEN
            RAISE EXCEPTION 'Provider receipts are immutable after processing' USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'billing_documentsequence' THEN
        IF previous - 'value' <> incoming - 'value' OR NEW.value <> OLD.value + 1 THEN
            RAISE EXCEPTION 'Document counters must advance by one' USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'billing_billingconfiguration' THEN
        IF OLD.id <> NEW.id OR OLD.created_at <> NEW.created_at THEN
            RAISE EXCEPTION 'Configuration identity is immutable' USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'billing_usersubscription' THEN
        IF OLD.plan_snapshot <> '{}'::jsonb AND
            (previous - 'status' <> incoming - 'status'
             OR NOT (OLD.status = NEW.status OR NEW.status = 'revoked' OR (OLD.status = 'active' AND NEW.status = 'expired'))) THEN
            RAISE EXCEPTION 'Subscription terms are immutable' USING ERRCODE = '23514';
        END IF;
    ELSE
        RAISE EXCEPTION 'Billing documents and audit evidence are append-only' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
"""


class Migration(migrations.Migration):
    dependencies = [("billing", "0008_documentsequence_financialauditevent_refundapproval_and_more")]
    operations = [migrations.RunSQL(
        FUNCTION + "\n".join(
            f"CREATE TRIGGER billing_history_guard BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION billing_guard_financial_history();" for table in TABLES),
        "\n".join(f"DROP TRIGGER IF EXISTS billing_history_guard ON {table};" for table in TABLES)
        + "\nDROP FUNCTION IF EXISTS billing_guard_financial_history();",
    )]

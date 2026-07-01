-- OLX Arbitrage system — PostgreSQL schema.
-- Implements a double-entry bookkeeping ledger with a DB-level balance
-- validation trigger, plus inventory and search-campaign tables.

-- ---------------------------------------------------------------------------
-- Chart of accounts
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ledger_accounts (
    id SERIAL PRIMARY KEY,
    code VARCHAR(10) UNIQUE NOT NULL,          -- e.g. '1010' cash, '1200' inventory
    name VARCHAR(100) NOT NULL,
    class VARCHAR(20) NOT NULL CHECK (class IN ('Asset', 'Liability', 'Equity', 'Revenue', 'Expense')),
    is_debit_positive BOOLEAN NOT NULL         -- balance grows on Debit (True) or Credit (False)
);

-- ---------------------------------------------------------------------------
-- Unique products participating in arbitrage flows
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS inventory_items (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    olx_offer_id VARCHAR(50) UNIQUE,
    purchase_price NUMERIC(12, 2) NOT NULL,
    estimated_market_price NUMERIC(12, 2) NOT NULL,
    status VARCHAR(50) DEFAULT 'purchased'
        CHECK (status IN ('purchased', 'in_transit', 'in_stock', 'refurbishing', 'sold', 'returned')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    sold_at TIMESTAMP WITH TIME ZONE
);

-- ---------------------------------------------------------------------------
-- Financial transactions and their double-entry journal lines
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS financial_transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    description TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS journal_lines (
    id SERIAL PRIMARY KEY,
    transaction_id UUID REFERENCES financial_transactions(id) ON DELETE CASCADE NOT NULL,
    account_id INTEGER REFERENCES ledger_accounts(id) NOT NULL,
    inventory_item_id INTEGER REFERENCES inventory_items(id),
    amount NUMERIC(12, 2) NOT NULL CHECK (amount > 0.0),
    is_debit BOOLEAN NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_journal_lines_acc ON journal_lines(account_id);
CREATE INDEX IF NOT EXISTS idx_journal_lines_tx ON journal_lines(transaction_id);

-- ---------------------------------------------------------------------------
-- Search campaigns (operator managed) and observed offers
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS search_campaigns (
    id SERIAL PRIMARY KEY,
    query VARCHAR(255) NOT NULL,
    category VARCHAR(100),
    status VARCHAR(20) NOT NULL DEFAULT 'training'
        CHECK (status IN ('training', 'active', 'paused')),
    market_price NUMERIC(12, 2),
    min_discount NUMERIC(5, 2) NOT NULL DEFAULT 20.0,   -- required discount %
    weight_kg NUMERIC(6, 2) NOT NULL DEFAULT 1.0,
    rejected_count INTEGER NOT NULL DEFAULT 0,
    scanned_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS offers (
    id SERIAL PRIMARY KEY,
    campaign_id INTEGER REFERENCES search_campaigns(id) ON DELETE CASCADE NOT NULL,
    olx_offer_id VARCHAR(50) NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    price NUMERIC(12, 2) NOT NULL,
    url VARCHAR(500),
    seller_account_age_days INTEGER,
    score NUMERIC(5, 2),
    discount NUMERIC(5, 2),
    net_profit NUMERIC(12, 2),
    is_deal BOOLEAN NOT NULL DEFAULT FALSE,
    risks TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    UNIQUE (campaign_id, olx_offer_id)
);

CREATE INDEX IF NOT EXISTS idx_offers_campaign ON offers(campaign_id);
CREATE INDEX IF NOT EXISTS idx_offers_deal ON offers(is_deal);

-- ---------------------------------------------------------------------------
-- Balance validation trigger: debits must equal credits per transaction
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION check_transaction_integrity_trigger()
RETURNS TRIGGER AS $$
DECLARE
    v_debit_total NUMERIC(12, 2);
    v_credit_total NUMERIC(12, 2);
BEGIN
    SELECT COALESCE(SUM(amount), 0.0) INTO v_debit_total
    FROM journal_lines
    WHERE transaction_id = NEW.transaction_id AND is_debit = TRUE;

    SELECT COALESCE(SUM(amount), 0.0) INTO v_credit_total
    FROM journal_lines
    WHERE transaction_id = NEW.transaction_id AND is_debit = FALSE;

    IF v_debit_total <> v_credit_total THEN
        RAISE EXCEPTION 'Double-entry balance violation: Debits (%) must equal Credits (%)',
            v_debit_total, v_credit_total;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- The trigger is DEFERRABLE + INITIALLY DEFERRED so a whole batch of lines can be
-- inserted inside one transaction and the balance is validated only at COMMIT.
DROP TRIGGER IF EXISTS trg_check_transaction_integrity ON journal_lines;
CREATE CONSTRAINT TRIGGER trg_check_transaction_integrity
    AFTER INSERT ON journal_lines
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW
    EXECUTE FUNCTION check_transaction_integrity_trigger();

-- ---------------------------------------------------------------------------
-- Seed chart of accounts (idempotent)
-- ---------------------------------------------------------------------------
INSERT INTO ledger_accounts (code, name, class, is_debit_positive) VALUES
    ('1010', 'Cash:BankCard',        'Asset',   TRUE),
    ('1200', 'Inventory:Products',   'Asset',   TRUE),
    ('3000', 'Equity:Owner',         'Equity',  FALSE),
    ('4000', 'Revenue:Sales',        'Revenue', FALSE),
    ('5000', 'Expense:ProductCost',  'Expense', TRUE),
    ('5100', 'Expense:Marketing',    'Expense', TRUE)
ON CONFLICT (code) DO NOTHING;

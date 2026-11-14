CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;

-- Usuários
CREATE TABLE IF NOT EXISTS users (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    display_name         TEXT   NOT NULL CHECK (btrim(display_name) <> ''),
    email                CITEXT NOT NULL UNIQUE,
    password_hash        TEXT   NOT NULL,
    monthly_income_cents BIGINT CHECK (monthly_income_cents >= 0),
    seller_enabled_at    TIMESTAMPTZ,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_users_name_trgm ON users USING gin (display_name gin_trgm_ops);

-- Sessões
CREATE TABLE IF NOT EXISTS sessions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id),
    token_hash  TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at  TIMESTAMPTZ NOT NULL,
    revoked_at  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions (user_id);

-- Itens
CREATE TABLE IF NOT EXISTS items (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id    UUID NOT NULL REFERENCES users(id),
    title       TEXT NOT NULL CHECK (btrim(title) <> ''),
    description TEXT NOT NULL CHECK (btrim(description) <> ''),
    category    TEXT NOT NULL CHECK (btrim(category) <> ''),
    photos      JSONB NOT NULL
                CHECK (jsonb_typeof(photos) = 'array' AND jsonb_array_length(photos) >= 3),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_items_owner      ON items (owner_id);
CREATE INDEX IF NOT EXISTS idx_items_category   ON items (category);
CREATE INDEX IF NOT EXISTS idx_items_title_trgm ON items USING gin (title gin_trgm_ops);

-- Leilões
CREATE TABLE IF NOT EXISTS auctions (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    item_id           UUID NOT NULL REFERENCES items(id),
    status            TEXT NOT NULL DEFAULT 'AGENDADO'
                      CHECK (status IN ('AGENDADO','EM_ANDAMENTO','VENDIDO','ENCERRADO_SEM_LANCES','CANCELADO')),
    start_price       BIGINT NOT NULL CHECK (start_price > 0),
    current_price     BIGINT NOT NULL,
    current_min_bid   BIGINT NOT NULL,
    leader_id         UUID REFERENCES users(id),
    bid_count         INT NOT NULL DEFAULT 0 CHECK (bid_count >= 0),
    starts_at         TIMESTAMPTZ NOT NULL,
    ends_at           TIMESTAMPTZ NOT NULL,
    original_ends_at  TIMESTAMPTZ NOT NULL,
    closed_at         TIMESTAMPTZ,
    cancelled_at      TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT ck_auction_times  CHECK (starts_at < original_ends_at AND ends_at >= original_ends_at),
    CONSTRAINT ck_auction_prices CHECK (
        (bid_count = 0 AND current_price = start_price AND current_min_bid = start_price)
        OR (bid_count > 0 AND current_price >= start_price AND current_min_bid > current_price)
    ),
    CONSTRAINT ck_auction_leader CHECK ((bid_count = 0) = (leader_id IS NULL)),
    CONSTRAINT ck_auction_final  CHECK (
        status IN ('AGENDADO','EM_ANDAMENTO')
        OR (status = 'VENDIDO' AND bid_count > 0)
        OR (status IN ('ENCERRADO_SEM_LANCES','CANCELADO') AND bid_count = 0)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_auctions_one_active_per_item
    ON auctions (item_id) WHERE status IN ('AGENDADO','EM_ANDAMENTO');

CREATE INDEX IF NOT EXISTS idx_auctions_status_times ON auctions (status, starts_at, ends_at);
CREATE INDEX IF NOT EXISTS idx_auctions_to_open      ON auctions (starts_at) WHERE status = 'AGENDADO';
CREATE INDEX IF NOT EXISTS idx_auctions_to_close     ON auctions (ends_at)   WHERE status = 'EM_ANDAMENTO';
CREATE INDEX IF NOT EXISTS idx_auctions_item         ON auctions (item_id);
CREATE INDEX IF NOT EXISTS idx_auctions_leader       ON auctions (leader_id) WHERE status = 'EM_ANDAMENTO';
CREATE INDEX IF NOT EXISTS idx_auctions_winner       ON auctions (leader_id) WHERE status = 'VENDIDO';

CREATE OR REPLACE FUNCTION auctions_guard_status() RETURNS trigger AS $$
BEGIN
    IF OLD.status IN ('VENDIDO','ENCERRADO_SEM_LANCES','CANCELADO') THEN
        RAISE EXCEPTION 'Leilão % está em estado final (%) e é imutável', OLD.id, OLD.status;
    END IF;
    IF NEW.status <> OLD.status AND NOT (
           (OLD.status = 'AGENDADO'     AND NEW.status IN ('EM_ANDAMENTO','CANCELADO'))
        OR (OLD.status = 'EM_ANDAMENTO' AND NEW.status IN ('VENDIDO','ENCERRADO_SEM_LANCES','CANCELADO'))
    ) THEN
        RAISE EXCEPTION 'Transição inválida: % -> %', OLD.status, NEW.status;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_auctions_guard_status ON auctions;
CREATE TRIGGER trg_auctions_guard_status
    BEFORE UPDATE ON auctions
    FOR EACH ROW EXECUTE FUNCTION auctions_guard_status();

-- Lances
CREATE TABLE IF NOT EXISTS bids (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    auction_id       UUID NOT NULL REFERENCES auctions(id),
    user_id          UUID NOT NULL REFERENCES users(id),
    amount           BIGINT NOT NULL CHECK (amount > 0),
    seq              INT NOT NULL,
    idempotency_key  UUID NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (auction_id, user_id, idempotency_key),
    UNIQUE (auction_id, seq),
    UNIQUE (auction_id, amount)
);
CREATE INDEX IF NOT EXISTS idx_bids_auction_created ON bids (auction_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_bids_user_created    ON bids (user_id, created_at DESC);

-- Presença na sala
CREATE TABLE IF NOT EXISTS auction_presence (
    auction_id    UUID NOT NULL REFERENCES auctions(id),
    user_id       UUID NOT NULL REFERENCES users(id),
    role          TEXT NOT NULL CHECK (role IN ('PARTICIPANTE','ESPECTADOR')),
    joined_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (auction_id, user_id)
);
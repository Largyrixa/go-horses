CREATE DATABASE IF NOT EXISTS leilao
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;
USE leilao;

-- Usuários (utf8mb4_0900_ai_ci já ignora maiúsculas e acentos em buscas e e-mail)
CREATE TABLE IF NOT EXISTS users (
    id                   CHAR(36) PRIMARY KEY,
    display_name         VARCHAR(150) NOT NULL,
    email                VARCHAR(255) NOT NULL UNIQUE,
    password_hash        VARCHAR(255) NOT NULL,
    monthly_income_cents BIGINT NULL,
    seller_enabled_at    DATETIME(6) NULL,
    created_at           DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT ck_users_name   CHECK (TRIM(display_name) <> ''),
    CONSTRAINT ck_users_income CHECK (monthly_income_cents IS NULL OR monthly_income_cents >= 0)
) ENGINE=InnoDB;

-- Sessões
CREATE TABLE IF NOT EXISTS sessions (
    id          CHAR(36) PRIMARY KEY,
    user_id     CHAR(36) NOT NULL,
    token_hash  CHAR(64) NOT NULL UNIQUE,
    created_at  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    expires_at  DATETIME(6) NOT NULL,
    revoked_at  DATETIME(6) NULL,
    INDEX idx_sessions_user (user_id),
    CONSTRAINT fk_sessions_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB;

-- Itens
CREATE TABLE IF NOT EXISTS items (
    id          CHAR(36) PRIMARY KEY,
    owner_id    CHAR(36) NOT NULL,
    title       VARCHAR(150) NOT NULL,
    description TEXT NOT NULL,
    category    VARCHAR(80) NOT NULL,
    photos      JSON NOT NULL,
    created_at  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    INDEX idx_items_owner    (owner_id),
    INDEX idx_items_category (category),
    CONSTRAINT fk_items_owner FOREIGN KEY (owner_id) REFERENCES users(id),
    CONSTRAINT ck_items_title CHECK (TRIM(title) <> ''),
    CONSTRAINT ck_items_desc  CHECK (TRIM(description) <> ''),
    CONSTRAINT ck_items_cat   CHECK (TRIM(category) <> ''),
    CONSTRAINT ck_items_photos CHECK (JSON_TYPE(photos) = 'ARRAY' AND JSON_LENGTH(photos) >= 3)
) ENGINE=InnoDB;

-- Leilões
CREATE TABLE IF NOT EXISTS auctions (
    id                CHAR(36) PRIMARY KEY,
    item_id           CHAR(36) NOT NULL,
    status            VARCHAR(30) NOT NULL DEFAULT 'AGENDADO',
    start_price       BIGINT NOT NULL,
    current_price     BIGINT NOT NULL,
    current_min_bid   BIGINT NOT NULL,
    leader_id         CHAR(36) NULL,
    bid_count         INT NOT NULL DEFAULT 0,
    starts_at         DATETIME(6) NOT NULL,
    ends_at           DATETIME(6) NOT NULL,
    original_ends_at  DATETIME(6) NOT NULL,
    closed_at         DATETIME(6) NULL,
    cancelled_at      DATETIME(6) NULL,
    created_at        DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    -- RF28: garante no banco apenas 1 leilão AGENDADO ou EM_ANDAMENTO por item
    active_item_id    CHAR(36) GENERATED ALWAYS AS (
        IF(status IN ('AGENDADO', 'EM_ANDAMENTO'), item_id, NULL)
    ) VIRTUAL,

    UNIQUE KEY uq_auctions_one_active_per_item (active_item_id),
    INDEX idx_auctions_status_times (status, starts_at, ends_at),
    INDEX idx_auctions_item         (item_id),
    INDEX idx_auctions_leader_status (leader_id, status),

    CONSTRAINT fk_auctions_item   FOREIGN KEY (item_id) REFERENCES items(id),
    CONSTRAINT fk_auctions_leader FOREIGN KEY (leader_id) REFERENCES users(id),
    CONSTRAINT ck_auction_status  CHECK (status IN ('AGENDADO','EM_ANDAMENTO','VENDIDO','ENCERRADO_SEM_LANCES','CANCELADO')),
    CONSTRAINT ck_auction_start   CHECK (start_price > 0),
    CONSTRAINT ck_auction_bids    CHECK (bid_count >= 0),
    CONSTRAINT ck_auction_times   CHECK (starts_at < original_ends_at AND ends_at >= original_ends_at),
    CONSTRAINT ck_auction_prices  CHECK (
        (bid_count = 0 AND current_price = start_price AND current_min_bid = start_price)
        OR (bid_count > 0 AND current_price >= start_price AND current_min_bid > current_price)
    ),
    CONSTRAINT ck_auction_leader  CHECK ((bid_count = 0) = (leader_id IS NULL)),
    CONSTRAINT ck_auction_final   CHECK (
        status IN ('AGENDADO','EM_ANDAMENTO')
        OR (status = 'VENDIDO' AND bid_count > 0)
        OR (status IN ('ENCERRADO_SEM_LANCES','CANCELADO') AND bid_count = 0)
    )
) ENGINE=InnoDB;

DELIMITER $$
CREATE TRIGGER trg_auctions_guard_status
BEFORE UPDATE ON auctions
FOR EACH ROW
BEGIN
    IF OLD.status IN ('VENDIDO', 'ENCERRADO_SEM_LANCES', 'CANCELADO') THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Leilão em estado final é imutável';
    END IF;

    IF NEW.status <> OLD.status AND NOT (
           (OLD.status = 'AGENDADO'     AND NEW.status IN ('EM_ANDAMENTO', 'CANCELADO'))
        OR (OLD.status = 'EM_ANDAMENTO' AND NEW.status IN ('VENDIDO', 'ENCERRADO_SEM_LANCES', 'CANCELADO'))
    ) THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Transição de estado inválida para o leilão';
    END IF;
END$$
DELIMITER ;

-- Lances
CREATE TABLE IF NOT EXISTS bids (
    id               CHAR(36) PRIMARY KEY,
    auction_id       CHAR(36) NOT NULL,
    user_id          CHAR(36) NOT NULL,
    amount           BIGINT NOT NULL,
    seq              INT NOT NULL,
    idempotency_key  CHAR(36) NOT NULL,
    created_at       DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    UNIQUE KEY uq_bids_idempotency (auction_id, user_id, idempotency_key),
    UNIQUE KEY uq_bids_seq         (auction_id, seq),
    UNIQUE KEY uq_bids_amount      (auction_id, amount),
    INDEX idx_bids_auction_created (auction_id, created_at DESC),
    INDEX idx_bids_user_created    (user_id, created_at DESC),

    CONSTRAINT fk_bids_auction FOREIGN KEY (auction_id) REFERENCES auctions(id),
    CONSTRAINT fk_bids_user    FOREIGN KEY (user_id) REFERENCES users(id),
    CONSTRAINT ck_bids_amount  CHECK (amount > 0)
) ENGINE=InnoDB;

-- Presença na sala
CREATE TABLE IF NOT EXISTS auction_presence (
    auction_id    CHAR(36) NOT NULL,
    user_id       CHAR(36) NOT NULL,
    role          VARCHAR(20) NOT NULL,
    joined_at     DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    last_seen_at  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (auction_id, user_id),
    CONSTRAINT fk_presence_auction FOREIGN KEY (auction_id) REFERENCES auctions(id),
    CONSTRAINT fk_presence_user    FOREIGN KEY (user_id) REFERENCES users(id),
    CONSTRAINT ck_presence_role    CHECK (role IN ('PARTICIPANTE', 'ESPECTADOR'))
) ENGINE=InnoDB;

-- Barramento de eventos em tempo real (substitui LISTEN/NOTIFY para multi-instância)
CREATE TABLE IF NOT EXISTS auction_events (
    id             BIGINT AUTO_INCREMENT PRIMARY KEY,
    auction_id     CHAR(36) NOT NULL,
    target_user_id CHAR(36) NULL,
    payload        JSON NOT NULL,
    created_at     DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    INDEX idx_events_created (created_at)
) ENGINE=InnoDB;

SHELL := /bin/bash

.PHONY: help db install generate push seed setup api web reset test test-security test-race bench

help:
	@echo "make db             - sobe o Postgres local (docker compose)"
	@echo "make install        - cria .venv e instala as dependências do backend"
	@echo "make generate       - gera o client do Prisma"
	@echo "make push           - cria/atualiza as tabelas no Postgres"
	@echo "make seed           - popula os dados de demonstração"
	@echo "make setup          - install + generate + push + seed"
	@echo "make api            - roda a API em http://localhost:8088"
	@echo "make web            - roda o frontend em http://localhost:8080"
	@echo "make reset          - apaga e recria os dados de demonstração"
	@echo "make test           - roda toda a suíte de testes (auth, SQLi, corridas, benchmark)"
	@echo "make test-security  - auth/autorização + SQL injection"
	@echo "make test-race      - corridas de lances/cancelamento"
	@echo "make bench          - benchmark de latência/throughput"

db:
	docker compose up -d db

install:
	cd backend && python3 -m venv .venv && .venv/bin/pip install -U pip && .venv/bin/pip install -r requirements.txt
	test -f backend/.env || cp backend/.env.example backend/.env

generate:
	cd backend && PATH="$$PWD/.venv/bin:$$PATH" .venv/bin/prisma generate

push:
	cd backend && PATH="$$PWD/.venv/bin:$$PATH" .venv/bin/prisma db push

seed:
	cd backend && .venv/bin/python seed.py

setup: install generate push seed

api:
	cd backend && .venv/bin/uvicorn app.main:app --reload --port 8088

web:
	cd frontend && npm run dev

reset: seed

test:
	cd backend && .venv/bin/python tests/run_all.py

test-security:
	cd backend && .venv/bin/python tests/test_auth.py && .venv/bin/python tests/test_sql_injection.py

test-race:
	cd backend && .venv/bin/python tests/test_race_auction.py

bench:
	cd backend && .venv/bin/python tests/benchmark.py

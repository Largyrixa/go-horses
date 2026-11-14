SHELL := /bin/bash

.PHONY: help db install generate push seed setup api web build reset

help:
	@echo "make db        - garante um Postgres em 127.0.0.1:5432 (reaproveita se já houver)"
	@echo "make install   - cria .venv e instala as dependências do backend"
	@echo "make generate  - gera o client do Prisma"
	@echo "make push      - cria/atualiza as tabelas no Postgres"
	@echo "make seed      - popula os dados de demonstração"
	@echo "make setup     - install + generate + push + seed"
	@echo "make api       - roda a API em http://localhost:8088"
	@echo "make web       - roda o frontend em http://localhost:8080 (instala deps se preciso)"
	@echo "make build     - gera o build de produção do frontend em frontend/dist"
	@echo "make reset     - apaga e recria os dados de demonstração"

db:
	@if (exec 3<>/dev/tcp/127.0.0.1/5432) 2>/dev/null; then \
		echo "Postgres já responde em 127.0.0.1:5432 — usando o banco existente (Docker não é necessário)."; \
	else \
		docker compose up -d db || { \
			echo ""; \
			echo "Não foi possível subir o Postgres via Docker."; \
			echo "Se o erro foi 'permission denied' em /var/run/docker.sock:"; \
			echo "  newgrp docker      # ou faça logout/login e tente de novo"; \
			echo "  # alternativa: sudo docker compose up -d db"; \
			exit 1; \
		}; \
	fi

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
	cd frontend && { [ -d node_modules ] || npm ci; }
	cd frontend && npm run dev

build:
	cd frontend && { [ -d node_modules ] || npm ci; }
	cd frontend && npm run build

reset: seed

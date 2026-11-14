# Go Horses — Leilão Online (Hackathon)

Plataforma de leilão online em tempo real: o comitente anuncia um item, os
compradores disputam lances ao vivo e o leilão abre/fecha sozinho, com vencedor.
O **frontend** já estava prototipado; este repositório agora tem também o
**backend completo** (FastAPI + Prisma + PostgreSQL), com banco populado para demo.

- **Produção prevista na VM:** <http://200.18.99.113:8028>
  (a porta pública 8028 é encaminhada para a **8080** dentro da VM; ver [Deploy](#deploy-na-vm))
- **API local:** <http://localhost:8088>
- **Documentação interativa (Swagger):** <http://localhost:8088/docs>
- **Frontend local:** <http://localhost:8080>

> **Portas:** frontend **8080**, backend **8088** e PostgreSQL **5432**.
> O 3306 é a porta padrão do MySQL; como o banco aqui é PostgreSQL, usamos 5432.

```
navegador
   │  http://200.18.99.113:8028  (port-forward para 8080)
   ▼
┌───────────────────────────── VM ─────────────────────────────┐
│ Caddy :8080                                                  │
│   ├── /            → frontend React (dist)                   │
│   ├── /api/        → uvicorn 127.0.0.1:8088 (REST + WS)      │
│   ├── /uploads/    → fotos enviadas                          │
│   └── /static/     → imagens de demonstração                 │
│                                                              │
│ uvicorn :8088 (FastAPI) ── Prisma ── PostgreSQL :5432        │
└──────────────────────────────────────────────────────────────┘
```

---

## 1. Rodar do zero (local)

Pré-requisitos: **Python 3.11+**, **Node 18+**, **PostgreSQL 14+** (ou Docker).
O Prisma usa Node para gerar o client.

### 1.1 Banco de dados

Com Docker (mais simples):

```bash
docker compose up -d db
```

Sem Docker, crie um banco/usuário no Postgres local:

```sql
CREATE USER gohorses WITH PASSWORD 'gohorses';
CREATE DATABASE gohorses OWNER gohorses;
```

A URL padrão em `backend/.env` é
`postgresql://gohorses:gohorses@localhost:5432/gohorses?schema=public`.
Se usar outro usuário/porta, ajuste `DATABASE_URL`.

### 1.2 Backend

```bash
cd backend
cp .env.example .env          # ajuste DATABASE_URL se precisar
python3 -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt

prisma generate               # gera o client Python a partir do schema
prisma db push                # cria as tabelas no Postgres
python seed.py                # popula contas e leilões de demonstração

uvicorn app.main:app --reload --port 8088
```

Se `prisma` não for encontrado mesmo com a venv ativa:

```bash
PATH="$PWD/.venv/bin:$PATH" .venv/bin/prisma generate
PATH="$PWD/.venv/bin:$PATH" .venv/bin/prisma db push
```

Atalho com Make (na raiz, depois de subir o banco):

```bash
make setup   # instala, gera o client, cria as tabelas e roda o seed
make api     # sobe a API em :8088
```

### 1.3 Frontend

Em outro terminal:

```bash
cd frontend
cp env.example .env.local   # opcional: os padrões já funcionam
npm install
npm run dev
```

Abra <http://localhost:8080>. O Vite repassa **os mesmos caminhos do Caddy**
para `http://127.0.0.1:8088`: `/api` (REST + WebSocket), `/uploads` (fotos
enviadas) e `/static` (imagens do seed). O front só usa URLs relativas, então
não há CORS nem host/porta fixos no bundle — o mesmo código roda em dev e em
produção.

Para ver o build de produção localmente (com o mesmo proxy, na porta 4173):

```bash
npm run build && npm run preview
```

### 1.4 Contas de demonstração

Senha de todas: **`senha1234`**

| E-mail | Papel | Observação |
|---|---|---|
| `ana@go-horses.dev` | comitente | anuncia itens |
| `bruno@go-horses.dev` | comprador | já lidera um leilão em andamento |
| `carla@go-horses.dev` | compradora | conta antiga (200 dias), testa pontuação |
| `diego@go-horses.dev` | comprador | venceu um leilão |
| `elisa@go-horses.dev` | comitente | anuncia itens |

O seed cria 6 leilões: **em andamento com lances**, **agendado (abre em 3 min)**,
**em andamento sem lances**, **vendido**, **encerrado sem lances** e **cancelado**.
As fotos são SVGs locais em `backend/static/demo/` (funcionam sem internet).

Para resetar os dados a qualquer momento:

```bash
cd backend && .venv/bin/python seed.py
# ou, na raiz:
make reset
```

> O seed **apaga** os dados atuais. Use só em desenvolvimento.

---

## 2. Como testar

1. Abra <http://localhost:8088/docs> e teste as rotas direto no Swagger.
2. No front, entre como `ana@go-horses.dev` e anuncie um item com **3 fotos**,
   início em **1 minuto** e duração de **3 minutos** (atalhos da tela).
3. Entre como `bruno@go-horses.dev` e dê lances na sala. Abra outra janela
   anônima como `carla@go-horses.dev` para ver o tempo real, o líder mudando e
   o aviso de "lance superado".
4. Deixe o leilão terminar: ele fecha sozinho como **Vendido** (com vencedor)
   ou **Encerrado sem lances**. Reinicie a API no meio de um leilão para ver a
   recuperação automática (RF18).

Exemplo de lance via `curl` (o `Idempotency-Key` é obrigatório — RF12):

```bash
TOKEN=$(curl -s http://localhost:8088/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"bruno@go-horses.dev","password":"senha1234"}' | jq -r .token)

AUCTION=$(curl -s 'http://localhost:8088/api/auctions?status=running' | jq -r '.items[0].id')

curl -s -X POST "http://localhost:8088/api/auctions/$AUCTION/bids" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: tente-1' \
  -d '{"amount": 30500}' | jq
```

Reenvie o mesmo `Idempotency-Key` e o servidor devolve **o mesmo lance**
(`"replayed": true`), sem duplicar. Mande o mesmo key com valor diferente: a
resposta original é mantida (RF12).

---

## 3. O que foi implementado

Referência: `Requisitos_Leilao_Hackathon.pdf`.

### Núcleo (obrigatório)

| Requisito | Como está |
|---|---|
| RF01 contas | cadastro/login com e-mail único, senha com scrypt |
| RF02 sessão | token opaco com hash no banco, expira em 7 dias; 401 encerra |
| RF03 comprador/comitente | todo usuário logado pode anunciar; sem administrador |
| RF04 listagem pública / sala privada | leilões públicos; sala exige Bearer; comitente não dá lance |
| RF05 leilão + fotos | nome, descrição, categoria, 3–10 fotos, preço inicial, início e duração |
| RF06 limites fáceis de alterar | constantes em `backend/app/config.py` |
| RF07 fotos | validação de tipo/tamanho; upload direto (storage local, ver decisões) |
| RF08 cancelamento | só o comitente; Agendado ou Em andamento sem lances; vira Cancelado |
| RN01 ciclo de vida | 5 estados e transições válidas; com lances só termina Vendido |
| RF09 sala em tempo real | WebSocket `/api/auctions/{id}/ws` com reconexão e ressincronização |
| RF10 lances | valida sessão, sala, estado, horário, comitente, líder, preço e crédito |
| RF11 concorrência | `SELECT ... FOR UPDATE` no Postgres serializa lances do leilão |
| RF12 idempotência | `Idempotency-Key` único por leilão; reenvio devolve o original |
| RF14 lance mínimo | calculado só no servidor, por faixa de preço (tabela do documento) |
| RF15 prorrogação | lance nos últimos 2 min empurra o fim para +2 min, máx. 30 min |
| RF16 relógio | horários UTC, `server_time` nas respostas, decisão no servidor |
| RF17 fechamento automático | processo de fundo a cada 0,5 s fecha com/sem vencedor |
| RF18 reinício | transições no banco; ao subir, abre/fecha o que passou |
| RF19 dinheiro/fuso | centavos inteiros; ISO UTC; formatação no navegador |
| RF20 listagem | pública, paginada (12), padrão Agendados + Em andamento |
| RNF01 hospedagem | guia completo da VM + Caddy + systemd em `deploy/` |
| RNF02 fluxos pela web | tudo que o Núcleo exige tem tela no front |
| RNF03 recriar do zero | este README |
| RNF04 dados de demo | `backend/seed.py` (5 contas, 6 leilões em estados diferentes) |

### Nível 2 / bônus (parcial, backend)

- RF13: limite de 500 ms entre lances do mesmo usuário (reenvio idempotente não é punido).
- RF21: busca combinável por trecho do nome, categoria e estado.
- RF22: perfil público em `GET /api/users/{id}` (sem e-mail) — ainda sem tela.
- RF24: reconexão automática do WebSocket e estado ressincronizado.
- RF25/RF26: espectador, contagem de participantes/espectadores e aviso de superado.
- RF27: "Minhas participações" com situação `leader` / `outbid` / `won`.
- RF29–RF32: pontuação e crédito calculados em `/api/auth/me`; dados de demo com
  rendas diferentes. A **exigência** de crédito no lance fica desligada por
  padrão (`ENFORCE_CREDIT=false`), porque o front atual não coleta renda.
  Ligue com `ENFORCE_CREDIT=true` para testar o bônus.

**Fora do escopo desta entrega:** edição de leilão (RF23), relistagem (RF28),
tela de perfil público, avaliações/reputação e administração (não existem no edital).

---

## 4. Contrato da API

Base: `/api`. Dinheiro em **centavos inteiros**; datas em **ISO UTC**;
autenticação `Authorization: Bearer <token>`. Erros:
`{"error": {"code": "...", "message": "...", "min_bid": 30500}}`.

| Método | Rota | Auth | O que faz |
|---|---|---|---|
| POST | `/auth/register` | — | `{display_name,email,password}` → 201 (409 e-mail repetido) |
| POST | `/auth/login` | — | `{email,password}` → `{token,user}` |
| POST | `/auth/logout` | sim | encerra a sessão |
| GET | `/auth/me` | sim | usuário + pontuação/crédito |
| GET | `/categories` | — | lista de categorias |
| GET | `/auctions?q&category&status&page` | — | `{items,has_more,server_time}` |
| GET | `/auctions/{id}` | — | detalhe público |
| POST | `/auctions` | sim | cria item + leilão (201) |
| POST | `/auctions/{id}/cancel` | sim | cancela (comitente; regras RF08) |
| GET | `/auctions/{id}/room` | sim | estado da sala + últimos lances |
| POST | `/auctions/{id}/bids` | sim | `{amount}` + `Idempotency-Key` → 201 `{bid,auction}` |
| GET | `/me/auctions` | sim | meus leilões |
| GET | `/me/participations` | sim | `[{auction,situation,my_top_bid}]` |
| GET | `/users/{id}` | — | perfil público do comitente (RF22) |
| POST | `/uploads/presign` | sim | `{filename,content_type,size}` → `{upload_url,public_url}` |
| PUT | URL retornada | assinatura | envia o arquivo |
| WS | `/auctions/{id}/ws?token=&role=participant\|spectator` | token | sala ao vivo |
| GET | `/health` | — | checagem da API + banco |

Estados: `scheduled`, `running`, `sold`, `unsold`, `cancelled`.

---

## 5. Decisões da equipe (seção 8 do edital)

- **Tempo real:** WebSocket com reconexão exponencial (1–8 s) no cliente; ao
  reconectar, um GET da sala ressincroniza o estado. Simples e suficiente para
  uma VM, sem broker externo.
- **Concorrência:** lock de linha (`SELECT ... FOR UPDATE`) na transação do
  lance. O primeiro a chegar tem prioridade; o segundo relê o preço já atualizado
  e é recusado se ficou abaixo do mínimo. Custo: lances do mesmo leilão
  serializam no banco (aceitável na escala do hackathon).
- **Idempotência:** chave gerada no navegador por tentativa/valor, única por
  leilão. Reenvio devolve o resultado original; nunca cria segundo lance.
- **Prorrogação:** 2 minutos a partir do lance, no máximo 30 minutos acumulados,
  conforme referência do documento. O término é gravado no banco (`ends_at`),
  então reinício não perde prorrogação.
- **Relógio:** o servidor é a única fonte da verdade. O front só desenha a
  contagem; um lance atrasado é recusado mesmo com o contador em tela.
- **Fechamento:** processo de fundo no próprio FastAPI (a cada 0,5 s) em vez de
  cron. Um `UPDATE` condicional atômico garante que fechar duas vezes não
  duplica nem sobrescreve resultado.
- **Dinheiro:** inteiros em centavos do começo ao fim; nada de float.
- **Fotos:** o edital pede storage em nuvem, mas não houve credenciais na VM.
  A entrega usa disco local atrás do contrato de presign (`/api/uploads/presign`
  + `PUT` assinado), servido pelo Caddy. Trocar por S3/R2 significa mudar só
  `backend/app/routers/uploads.py`; o front não muda.
- **Sessão:** token opaco de 7 dias com hash no banco (permite logout real e
  revogação), em vez de JWT sem estado.
- **Um worker no uvicorn:** as contagens de participantes/espectadores são em
  memória por processo. Com vários workers os lances continuam corretos, mas
  cada socket aparece só no processo que o atende.
- **README:** publicado, com contas de demo, como recriar do zero e estas
  decisões — como o edital exige.

---

## 6. Variáveis de ambiente

### Backend (`backend/.env`)

| Variável | Padrão | Para que serve |
|---|---|---|
| `DATABASE_URL` | `postgresql://gohorses:gohorses@localhost:5432/gohorses?schema=public` | conexão do Prisma |
| `SECRET_KEY` | — | assina URLs de upload; troque em produção |
| `CORS_ORIGINS` | `http://localhost:8080,...` | origens liberadas (separadas por vírgula) |
| `PUBLIC_BASE_URL` | vazio | base opcional das URLs de fotos; vazio = caminhos relativos |
| `UPLOAD_DIR` | `./uploads` | pasta dos arquivos enviados |
| `UPLOAD_MAX_BYTES` | `5242880` | tamanho máximo por foto (5 MB) |
| `SESSION_TTL_DAYS` | `7` | validade da sessão |
| `ENFORCE_CREDIT` | `false` | liga a exigência de crédito do bônus (RF32) |
| `SYNC_INTERVAL_SECONDS` | `0.5` | intervalo do abridor/fechador automático |

### Frontend (`frontend/.env.local`)

| Variável | Padrão | Para que serve |
|---|---|---|
| `VITE_API_URL` | vazio | vazio = `/api` na mesma origem (proxy do Vite/Caddy) |
| `VITE_PROXY_TARGET` | `http://127.0.0.1:8088` | destino do proxy em dev |
| `VITE_WS_URL` | vazio | vazio = mesma origem da API |
| `VITE_MIN_PHOTOS` / `VITE_MAX_PHOTOS` | `3` / `10` | limites no formulário |
| `VITE_MAX_PHOTO_MB` | `5` | tamanho máximo no formulário |

**Por que `PUBLIC_BASE_URL` fica vazio:** as fotos são servidas pelo próprio
sistema, então a API devolve caminhos relativos (`/uploads/...`, `/static/...`).
Quem resolve a origem é o navegador: o proxy do Vite em dev e o Caddy em
produção. Assim o mesmo banco e o mesmo build funcionam nos dois ambientes, sem
CORS, sem URL fixa no bundle e sem re-rodar o seed ao trocar de host/porta.
Se o banco já tiver URLs absolutas antigas (ex.: `http://localhost:8088/...`),
o serializer reduz para o caminho automaticamente. Preencha só se as fotos
forem para outra origem (S3/R2).

---

## 7. Deploy na VM

Informações das imagens do WhatsApp: IP público **200.18.99.113**, equipe
**Go Horses = porta 8028**, o frontend **obrigatoriamente escuta na 8080**
dentro da VM; o port-forward da organização leva `8028 → 8080`. O acesso SSH
usa a porta e a chave enviadas ao capitão por e-mail (o slide mostra
`ssh -i ~/.ssh/hackaton -p <porta> ubuntu@200.18.99.113`).

### 7.1 Pacotes e banco

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip postgresql caddy nodejs npm git
sudo -u postgres psql -c "CREATE USER gohorses WITH PASSWORD 'gohorses';"
sudo -u postgres psql -c "CREATE DATABASE gohorses OWNER gohorses;"
```

### 7.2 Código e backend

```bash
sudo mkdir -p /opt/gohorses && sudo chown -R ubuntu:ubuntu /opt/gohorses
git clone <URL_DO_REPOSITORIO> /opt/gohorses
cd /opt/gohorses/backend

cp .env.example .env
nano .env
# DATABASE_URL="postgresql://gohorses:gohorses@localhost:5432/gohorses?schema=public"
# PUBLIC_BASE_URL=   # deixe vazio: as fotos usam URLs relativas atrás do Caddy
# CORS_ORIGINS="http://200.18.99.113:8028"
# SECRET_KEY="<uma string longa aleatória>"

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
prisma generate
prisma db push
python seed.py
```

Instale o serviço:

```bash
sudo cp /opt/gohorses/deploy/gohorses-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now gohorses-api
curl http://127.0.0.1:8088/api/health
```

### 7.3 Frontend + Caddy

```bash
cd /opt/gohorses/frontend
npm ci
# VITE_API_URL e VITE_WS_URL vazios: mesma origem via Caddy
npm run build

sudo mkdir -p /var/www/gohorses/frontend
sudo cp -r dist /var/www/gohorses/frontend/
# O Caddy roda como usuário caddy e precisa ler os arquivos estáticos:
sudo chmod -R a+rX /var/www/gohorses/frontend/dist

# Se o nginx estiver instalado na VM, desligue para não disputar a 8080:
sudo systemctl disable --now nginx 2>/dev/null || true

sudo cp /opt/gohorses/deploy/Caddyfile /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl enable --now caddy
sudo systemctl reload caddy
```

Abra <http://200.18.99.113:8028>. O `Caddy` escuta **8080** na VM; a
organização encaminha a **8028** pública para ela.

> **Fotos:** com `PUBLIC_BASE_URL` vazio a API devolve `/uploads/...` e
> `/static/...`, e o Caddy já encaminha os dois para o backend. Não precisa
> re-rodar o seed ao publicar na VM; só preencha `PUBLIC_BASE_URL` se as fotos
> saírem para outro storage (S3/R2).
>
> **WebSocket:** o `reverse_proxy` do Caddy já trata `Upgrade`/`Connection`
> automaticamente; não precisa de configuração extra para a sala.
>
> **Caddy no Arch:** `sudo pacman -S caddy` e o arquivo também fica em
> `/etc/caddy/Caddyfile`.
>
> **Caddy em Ubuntu:** se o pacote não estiver no repositório padrão, use o
> repositório oficial em <https://caddyserver.com/docs/install#debian-ubuntu-raspbian>.

### 7.4 Atualizar uma nova versão

```bash
cd /opt/gohorses
git pull
cd backend && source .venv/bin/activate && pip install -r requirements.txt
prisma db push
sudo systemctl restart gohorses-api

cd ../frontend && npm ci && npm run build
sudo rm -rf /var/www/gohorses/frontend/dist
sudo cp -r dist /var/www/gohorses/frontend/
sudo chmod -R a+rX /var/www/gohorses/frontend/dist
# Se o Caddyfile mudou:
sudo cp /opt/gohorses/deploy/Caddyfile /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

---

## 8. Estrutura do repositório

```
go-horses/
├── backend/
│   ├── app/
│   │   ├── main.py              FastAPI, CORS, ciclo de vida, ticker
│   │   ├── auction_service.py   regras: lances, ciclo, crédito, sync
│   │   ├── realtime.py          salas WebSocket
│   │   ├── serializers.py       modelo Prisma → JSON do front
│   │   ├── security.py          scrypt + tokens de sessão
│   │   ├── config.py            env e limites
│   │   ├── schemas.py           entrada Pydantic
│   │   ├── errors.py            erros no formato do front
│   │   ├── deps.py              Bearer/sessão
│   │   └── routers/             auth, auctions, me, uploads
│   ├── prisma/schema.prisma     User, Session, Item, Auction, Bid
│   ├── static/demo/             fotos SVG do seed
│   ├── seed.py                  dados de demonstração
│   ├── requirements.txt
│   └── .env.example
├── frontend/                    protótipo React/Vite já existente
├── deploy/                      Caddyfile + systemd da VM
├── docker-compose.yml           Postgres local
├── Makefile
└── README.md
```

---

## 9. Problemas comuns

| Sintoma | Causa / solução |
|---|---|
| `prisma-client-py: command not found` | Ative a venv ou use `PATH="$PWD/.venv/bin:$PATH" .venv/bin/prisma generate` |
| `Can't reach database server` | Postgres não subiu ou `DATABASE_URL` errada (`docker compose up -d db`) |
| `DATABASE_URL não configurada` | Falta `backend/.env`; copie do `.env.example` |
| Front chama API e dá erro de rede | Backend está em `:8088`? O proxy do Vite aponta para lá |
| Erro de CORS no navegador | Em dev use o proxy; se chamar a API direto, inclua a origem em `CORS_ORIGINS` |
| Fotos não aparecem | Em dev, veja se a API está em `:8088` (o proxy cobre `/uploads` e `/static`); em produção, se o Caddy está com os proxies e o `chmod a+rX` no `dist` |
| `npm run dev` diz que a 8080 está em uso | O Caddy (ou outro Vite) está escutando; pare um deles. O `npm run preview` usa a 4173 justamente para não brigar |
| Sala não atualiza | WebSocket bloqueado: veja `journalctl -u caddy -f`; o Caddy já faz o upgrade sozinho |
| `401` e volta ao login | Sessão expirou (7 dias) ou usuário fez logout em outra aba |
| Reiniciei e o leilão fechou | Correto: RF18 manda abrir/fechar o que passou do horário |
| Seed sem fotos | As imagens são locais (`backend/static/demo/`); confira se o Caddy/Vite repassa `/static` |

# Go Horses — Leilão Online (Hackathon)

Plataforma de leilão online em tempo real: o comitente anuncia um item, os
compradores disputam lances ao vivo e o leilão abre/fecha sozinho, com vencedor.
O **frontend** já estava prototipado; este repositório agora tem também o
**backend completo** (FastAPI + Prisma + PostgreSQL), com banco populado para demo.

- **Produção na VM:** <http://200.18.99.113:8088>
  (a porta pública 8088 é encaminhada para a **8080** dentro da VM; ver [Deploy](#deploy-na-vm))
- **API local:** <http://localhost:8088>
- **Documentação interativa (Swagger):** <http://localhost:8088/docs>
- **Frontend local:** <http://localhost:8080>

> **Portas:** frontend **8080**, backend **8088** e PostgreSQL **5432**.
> O 3306 é a porta padrão do MySQL; como o banco aqui é PostgreSQL, usamos 5432.

```
navegador
   │  http://200.18.99.113:8088  (port-forward para 8080)
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

Senha de todas: a definida em `SEED_PASSWORD` no `backend/.env`. Sem essa
variável, o `make seed` gera uma senha aleatória e mostra no terminal. Não
publique um ambiente com senha de demonstração conhecida. Para os exemplos de
`curl` abaixo, exporte a mesma senha no shell
(`export SEED_PASSWORD='sua-senha'`).

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
  -d '{"email":"bruno@go-horses.dev","password":"'"$SEED_PASSWORD"'"}' | jq -r .token)

AUCTION=$(curl -s 'http://localhost:8088/api/auctions?status=running' | jq -r '.items[0].id')

curl -s -X POST "http://localhost:8088/api/auctions/$AUCTION/bids" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: tente-1' \
  -d '{"amount": 30500}' | jq
```

Reenvie o mesmo `Idempotency-Key` e o servidor devolve **o mesmo lance**
(`"replayed": true`), sem duplicar. Reutilizar a mesma chave com outro valor é
recusado com `409 idempotency_key_reused` (RF12).

### 2.1 Suíte automatizada

Além do teste manual acima, o backend tem uma suíte de caixa-preta em
`backend/tests/`. Ela fala com a API via HTTP/WebSocket e não importa o código
da aplicação.

```bash
make test             # auth + SQL injection + corridas + benchmark
make test-security    # auth/autorização + SQL injection
make test-race        # concorrência de lances/cancelamento
make bench            # benchmark de latência
make load ARGS="--mode both --users 10,50,100"   # carga/capacidade
```

Os testes criam usuários e leilões de teste; use um banco descartável ou rode
`make reset` depois. As opções e o detalhamento de cada script estão em
[`backend/tests/README.md`](backend/tests/README.md). Os resultados da última
execução local estão na seção 10.

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
| WS | `/auctions/{id}/ws?role=participant\|spectator` | token na 1ª mensagem: `{"type":"auth","token":"..."}` (até 3 s após abrir) | sala ao vivo |
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
| `SECRET_KEY` | — | assina URLs de upload; use um valor próprio com 16+ caracteres (o de exemplo é ignorado e vira uma chave aleatória por processo) |
| `CORS_ORIGINS` | `http://localhost:8080,...` | origens de OUTROS sites autorizadas a chamar a API (separadas por vírgula; `*` não é aceito) |
| `SEED_PASSWORD` | aleatória | senha das contas criadas pelo `make seed` |
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

IP público **200.18.99.113**. O site é acessado em **8088**: o port-forward da
organização leva `8088 → 8080`, e o Caddy/frontend escuta **8080** dentro da
VM. O SSH usa a porta **8028** (`8028 → 22`), com a chave enviada ao capitão:

```bash
ssh -i ~/.ssh/hackaton -p 8028 ubuntu@200.18.99.113
```

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
# CORS_ORIGINS="http://200.18.99.113:8088"
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

Abra <http://200.18.99.113:8088>. O `Caddy` escuta **8080** na VM; a
organização encaminha a **8088** pública para ela. A **8028** é o SSH
(`8028 → 22`) e não deve ser usada pelo site.

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
│   ├── tests/                   auth, SQL injection, corridas, benchmark e carga
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

---

## 10. Testes automatizados e resultados

> Execução local de referência em **14/11/2026**, com Postgres descartável e a
> API em `127.0.0.1:8088`, uvicorn em **um worker**. O cliente dos testes rodou
> na mesma máquina. **Não são números da VM**; use como linha de base e para
> reproduzir o método.

### 10.1 Suíte funcional e de segurança

| Script | Verificações | Resultado |
|---|---:|---|
| `test_auth.py` | 70/70 | OK |
| `test_sql_injection.py` | 183/183 | OK |
| `test_race_auction.py` (5 rodadas) | 74/74 | OK |
| `test_race_auction.py --rounds 10` | 89/89 | OK |

O `run_all.py` terminou com `Resultado: OK` (auth, SQL injection, corridas e
benchmark). A corrida `cancel × bid` foi validada nas 10 rodadas: **exatamente
uma operação vence**. Se o lance vence, o cancelamento recebe `has_bids`; no
caminho determinístico cancelar-depois-lançar, o lance recebe `auction_closed` e
`bid_count` continua 0. Essa condição de corrida foi encontrada pela própria
suíte e corrigida com o mesmo `SELECT ... FOR UPDATE` usado nos lances.

### 10.2 Benchmark de leitura

`benchmark.py --requests 300 --concurrency 20 --warmup 20`:

| Endpoint | RPS | p50 | p95 | p99 | Erros |
|---|---:|---:|---:|---:|---:|
| `GET /api/health` | 563,2 | 28,5 ms | 73,7 ms | 89,6 ms | 0 |
| `GET /api/categories` | 749,9 | 17,7 ms | 81,0 ms | 112,1 ms | 0 |
| `GET /api/auctions` | 186,4 | 97,0 ms | 187,7 ms | 229,6 ms | 0 |
| `GET /api/auctions/{id}` | 214,6 | 84,1 ms | 175,8 ms | 217,3 ms | 0 |
| `GET /api/auctions/{id}/room` | 137,3 | 134,9 ms | 235,3 ms | 302,6 ms | 0 |

### 10.3 Teste de carga

Rampa HTTP com SLA de **p95 ≤ 500 ms**, 4 s por nível:

| Usuários | RPS | p50 | p95 | p99 | Erros | CPU uvicorn | Resultado |
|---:|---:|---:|---:|---:|---:|---:|---|
| 25 | 148,4 | 147,8 ms | 345,0 ms | 419,2 ms | 0% | ~100% | OK |
| 50 | 151,0 | 298,4 ms | 600,4 ms | 821,0 ms | 0% | ~99% | Falhou no SLA |
| 100 | 133,3 | 633,3 ms | 1,41 s | 1,88 s | 0% | ~99% | Falhou no SLA |

Todas as requisições responderam sem erro; o limite foi **latência/CPU**. Com
SLA de 500 ms, a capacidade estimada ficou em **25 usuários simultâneos** no
ambiente local. O processo do uvicorn já fica em ~100% de CPU nesse nível, então
o gargalo é o **worker único**, não a taxa de erro.

WebSocket na mesma sala:

| Conexões | Conectadas | Mensagens | Handshake p95 | 1ª msg p95 | Erros | CPU uvicorn | SLA | Resultado |
|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 10 | 10 | 106 | 10,7 ms | 74,4 ms | 0% | 3,6% | 1 s | OK |
| 25 | 25 | 693 | 17,6 ms | 155,4 ms | 0% | 8,1% | 1 s | OK |
| 50 | 50 | 2.505 | 65,3 ms | 452,0 ms | 0% | 17,3% | 1 s | OK |
| 100 | 100 | 8.324 | 35,1 ms | 404,5 ms | 0% | 29,3% | 500 ms | OK |
| 250 | 250 | 42.709 | 30,1 ms | 682,0 ms | 0% | 57,3% | 500 ms | Falhou no SLA |

O servidor **aceitou todas as conexões** testadas (até 250). Com SLA de 500 ms, a
capacidade estimada ficou em **100 conexões simultâneas**; 250 conexões foram
aceitas, mas a primeira mensagem p95 ficou em 682 ms. O número de mensagens
cresce bem mais que o de conexões porque cada nova conexão dispara um broadcast
de estado para a sala inteira; é o ponto natural de otimização se a sala
precisar de centenas de espectadores.

### 10.4 Como reproduzir e interpretar

```bash
# suíte funcional + benchmark
make test

# carga HTTP (SLA de 500 ms)
make load ARGS="--mode http --users 25,50,100 --http-duration 4 \
  --sla-p95-ms 500 --keep-going --server-pid $(pgrep -f 'uvicorn app.main')"

# carga WebSocket
make load ARGS="--mode ws --users 50,100,250 --ws-hold 30 \
  --sla-p95-ms 1000 --server-pid $(pgrep -f 'uvicorn app.main')"
```

- Para medir a VM, rode de **outra máquina** com
  `--base-url http://200.18.99.113:8088`.
- O cliente também pode ser o gargalo; acompanhe CPU/RSS com `--server-pid`.
- O teste cria usuários/leilões de carga. Rode em banco descartável ou limpe
  com `make reset`.
- Não execute cargas altas contra produção sem autorização.

Os números acima são uma referência local. O caminho mais direto para aumentar a
capacidade HTTP é reduzir o custo do caminho de leitura (por exemplo, o
`sync_auctions` executado em cada listagem/detalhe) ou avaliar múltiplos
workers; no caso de WebSocket, múltiplos workers exigem sessões fixas ou um
broker compartilhado, porque as salas e contadores são mantidos em memória por
processo.

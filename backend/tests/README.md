# Testes do Go Horses

Suíte de caixa-preta (via HTTP) para a API do Go Horses. Os scripts **não
importam o código da aplicação** e não precisam de pytest: usam apenas `httpx`,
que já está no `backend/requirements.txt`.

## Pré-requisitos

- API rodando (`make api` ou uvicorn) e banco acessível.
- Python da venv do backend, com as dependências instaladas.
- O banco pode estar populado pelo seed ou não; os scripts criam os próprios
  usuários e leilões.

```bash
make db          # se estiver usando Docker
make setup       # instala dependências, cria tabelas e roda o seed
make api         # terminal 1
```

## Executar tudo

```bash
make test
# equivale a:
cd backend
.venv/bin/python tests/run_all.py
```

O `run_all.py` faz um preflight em `/api/health`, executa os testes de
autenticação, SQL injection e corridas, e depois um benchmark rápido. Retorna
`0` somente se todos passarem.

## Executar cada parte

```bash
cd backend

# Autenticação/autorização: 401 sem token, 403 entre usuários, uploads, WS
.venv/bin/python tests/test_auth.py

# SQL injection em query, path, login, cadastro e Idempotency-Key
.venv/bin/python tests/test_sql_injection.py

# Corridas de lances, idempotência concorrente e cancelamento x lance
.venv/bin/python tests/test_race_auction.py

# Benchmark de latência/throughput (somente leitura por padrão)
.venv/bin/python tests/benchmark.py
```

Atalhos no Makefile:

```bash
make test-security   # auth + SQL injection
make test-race       # corridas de leilão
make bench           # benchmark
```

## Configuração

Todos os scripts aceitam `--base-url` e também leem `GOHORSES_API`:

```bash
cd backend
.venv/bin/python tests/run_all.py --base-url http://127.0.0.1:8088
GOHORSES_API=http://127.0.0.1:8088 .venv/bin/python tests/test_auth.py
```

O benchmark usa, por padrão, a conta de seed `bruno@go-horses.dev`
(`senha1234`). Para outra conta:

```bash
.venv/bin/python tests/benchmark.py \
  --email carla@go-horses.dev --password senha1234
```

Se o login falhar, o benchmark continua e apenas pula as rotas autenticadas.

## O que é verificado

### `test_auth.py`

- Todas as ações protegidas sem token retornam `401` com código `unauthorized`:
  criação/cancelamento de leilão, lance, sala, `/auth/me`, logout,
  `/me/auctions`, `/me/participations` e presign de upload.
- Token inexistente, esquema `Basic`, `Bearer` vazio e token aleatório: `401`.
- Token na query string não autentica rotas REST.
- Logout invalida o token.
- Comprador não cancela leilão de outro (`403 not_seller`).
- Comitente não dá lance no próprio leilão (`403 seller_cannot_bid`).
- Leilão em andamento com lances não pode ser cancelado (`409 has_bids`).
- Listagens `/me/*` não vazam dados de outro usuário.
- Perfil público não expõe e-mail.
- Upload: token adulterado, chave trocada, content-type errado e corpo maior
  que o declarado são rejeitados; upload válido é servido na URL pública.
- WebSocket sem token/inválido fecha com `4401`; autenticado recebe o estado.

### `test_sql_injection.py`

- Payloads clássicos (`' OR '1'='1`, `DROP TABLE`, `UNION SELECT`, `pg_sleep`,
  comentários SQL) em `q`, `category`, `status`, `page`, path params, login,
  cadastro, nome/descrição de leilão e `Idempotency-Key`.
- Nenhuma resposta `5xx`, nenhum stack trace/detalhe do banco.
- Payload `pg_sleep` não pode atrasar a resposta (consulta parametrizada).
- Strings maliciosas são armazenadas/retornadas literalmente.
- Após os ataques, health, login, listagem e contagem de lances continuam
  íntegros.

### `test_race_auction.py`

- Vários usuários enviam o mesmo lance mínimo simultaneamente: exatamente um
  `201`; os demais recebem `409`/`429`.
- Nova rodada com o novo mínimo: preço monotônico e `bid_count` coerente.
- Mesma `Idempotency-Key` enviada 5 vezes em paralelo: um único `bid.id`, um
  único lance no banco, uma resposta original e quatro replays.
- Mesma chave com valor diferente devolve o resultado original.
- Corrida entre `cancel` e `bid`: o leilão não pode terminar cancelado com
  lances. O script repete a rodada (`--rounds`, padrão 5) e falha se o leilão
  terminar cancelado com lances. É o teste de regressão da correção de
  `cancel_auction` (row lock).

Opções úteis:

```bash
.venv/bin/python tests/test_race_auction.py --bidders 20 --rounds 10
```

#### Corrida cancel × bid

`cancel_auction` usa a mesma transação com `SELECT ... FOR UPDATE` de
`place_bid`: se o cancelamento pegar o lock primeiro, o lance espera e recebe
`auction_closed`; se o lance pegar primeiro, o cancelamento lê `bid_count=1` e
recebe `has_bids`. O teste `test_race_auction.py` cobre os dois desfechos (a
corrida concorrente e o caminho determinístico cancelar-depois-lançar) e deve
passar com 0 falhas.

### `benchmark.py`

- Mede `GET /api/health`, `/api/categories`, `/api/auctions`,
  `/api/auctions/{id}` e `/api/auctions/{id}/room` (autenticado).
- Relata requisições, erros, RPS, p50/p90/p95/p99 e máximo.
- `--json arquivo.json` salva os resultados.
- `--max-p95-ms 250` faz o script falhar se algum endpoint passar do limite.
- `--include-login` inclui o `POST /api/auth/login` (scrypt é caro de propósito).
- Não cria lances nem altera dados por padrão.

## Dados de teste e limpeza

Os testes criam contas no formato
`teste+<prefixo>-<uuid>@go-horses.dev` e leilões próprios. Como a API não tem
endpoint de exclusão, esses dados permanecem no banco. Use um banco descartável
ou rode o seed para limpar:

```bash
make reset
```

> `make reset` (ou `python seed.py`) **apaga todos os dados atuais**. Use apenas
> em desenvolvimento/teste.

Leilões criados com lances não podem ser cancelados; eles fecham sozinhos pelo
ticker do backend (RF17). Os leilões de corrida usam duração curta justamente
para não ficarem abertos por muito tempo.

## Segurança e escopo

- Rode a suíte apenas contra ambiente próprio/de teste. Os payloads de SQL
  injection e as corridas geram tráfego agressivo.
- O teste de corrida **não mascara falhas**: se o invariante for violado, ele
  mostra os status/códigos e termina com código de saída diferente de zero.
- O benchmark é somente leitura por padrão; para carga de escrita, use os testes
  de corrida em um banco descartável.

## Estrutura

```
backend/tests/
├── common.py              # cliente, login/registro, criação de leilão, asserts
├── test_auth.py           # autenticação e autorização
├── test_sql_injection.py  # injeção SQL
├── test_race_auction.py   # concorrência de lances/cancelamento
├── benchmark.py           # benchmark HTTP
├── run_all.py             # orquestrador da suíte
└── README.md
```

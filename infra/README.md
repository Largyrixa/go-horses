# Leilão Online – Go Horses

**Endereço do sistema:** http://200.18.99.113:8088

## Como a VM está organizada

A organização publica o site na **8088** e o SSH na **8028**, mas o encaminhamento não é
1:1: o público `8088` chega na **8080** da VM e o público `8028` chega na **22** (sshd).
Nenhum serviço da aplicação usa a 8028.

```
navegador ──► :8088 ──(NAT)──► VM:8080 ──► proxy (Caddy :8088)
                                             ├─ /api/* ──► api (HTTP + WebSocket, :8088 interna)
                                             └─ resto   ──► front (nginx, :8080 interna)
                                           api / worker ──► MySQL 8 (sem porta pública)
fotos ──► armazenamento em nuvem da organização
```

| Porta | Onde | Serviço |
|-------|------|---------|
| **8088** | pública (NAT) | endereço do site → encaminha para VM:8080 |
| 8080 | host da VM | Caddy (único port publicado pelo Docker) |
| 8080 | interna (Docker) | nginx servindo o front compilado |
| 8088 | interna (Docker) | backend FastAPI (uvicorn) |
| 3306 | interna (Docker) | MySQL 8 |
| **8028** | pública (NAT) | SSH → VM:22 (não é serviço da aplicação) |

**Regras para quem escreve o código:**
- O navegador só conhece a origem **`http://IP:8088`**. O front usa caminhos relativos:
  `fetch("/api/leiloes")` e WebSocket em `/api/.../ws`. Nada de IP ou porta fixos — e por isso
  não existe CORS para configurar.
- O Caddy remove o prefixo **`/api`** antes de repassar ao backend (`handle_path`). Ou seja,
  no FastAPI as rotas são `/leiloes`, `/auth/login` etc.; o `/api` é responsabilidade do proxy.
- A API escuta na porta definida por `PORT` (**8088** dentro do contêiner).
- Rotas novas do front continuam relativas; qualquer coisa fora de `/api/*` cai no `index.html`
  (SPA), então não é preciso configurar rota no nginx.

## Acessar a VM

```bash
chmod 600 chave
ssh -i chave -p 8028 ubuntu@200.18.99.113
```

A chave nunca vai para o Git. Para o front e a API de fora, só vale a porta 8088.

## Atualizar a VM

```bash
./deploy.sh --force      # git pull + build do front + docker compose up -d --build
```

Deploy automático a cada minuto: veja o comentário no topo do `deploy.sh`.
O script usa a branch `main` por padrão; para deployar outra branch: `BRANCH=infra ./deploy.sh --force`.

## Recriar o ambiente do zero (RNF03)

```bash
cp .env.example .env     # preencher DB_PASSWORD e as credenciais do armazenamento
docker compose up -d --build
```

Pré-requisito: Docker com o plugin Compose (`sudo apt-get install -y docker.io docker-compose-v2`).

Os dados do MySQL ficam no volume `mysqldata` e o `backend/schema.sql` roda **só na primeira**
criação do volume. Mudou o schema? `docker compose down -v` e suba de novo.


## Contas de demonstração (RNF04)

| Papel      | E-mail | Senha |
|------------|--------|-------|
| Comitente  |        |       |
| Comprador 1|        |       |
| Comprador 2|        |       |
| Comprador 3|        |       |

## Decisões da equipe (seção 8, uma ou duas frases cada)

| Requisito | Decisão | Por quê |
|-----------|---------|---------|
| RF02 – sessão (duração, renovação) | | |
| RF05 – categorias e limites (texto, fotos, antecedência, duração) | | |
| RF07 – tipos e tamanhos de foto aceitos | | |
| RF09 – tecnologia de tempo real, lances recentes, como identificar o líder | | |
| RF14 – regra do lance mínimo | | |
| RF15 – regra de prorrogação e limite | | |
| RF20 – o que a listagem mostra, ordem e comportamento com muitos leilões | | |
| RNF01 – como os componentes estão organizados na VM | Docker Compose: Caddy (única porta pública, 8088), front nginx (8080), api FastAPI (8088), db MySQL 8, worker | Uma origem só: sem CORS e um único ponto de entrada |
| RF13 – limite de frequência de lances (Nível 2) | | |
| RF21 – busca (grafias, apresentação) (Nível 2) | | |
| RF23 – edição/cancelamento (Nível 2) | | |

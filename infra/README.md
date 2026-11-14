# Leilão Online – Go Horses

**Endereço do sistema:** http://200.18.99.113:8088

## Como a VM está organizada

Há uma única porta web pública, a **8088**, que a organização encaminha para a **8080** da VM.
(A porta pública **8028** é o SSH. Não use para serviços.)

```
navegador ──► :8088 ──► VM:8080 ──► proxy (Caddy)
                                      ├─ /api/*  e  /ws*  ──► api (HTTP + WebSocket, porta 8028 interna)
                                      └─ todo o resto     ──► front compilado
                                    api / worker ──► Postgres
fotos ──► armazenamento em nuvem da organização
```

**Regras para quem escreve o código:**
- Todas as rotas da API ficam sob **`/api`** (ex.: `/api/leiloes`), e o WebSocket em **`/ws`**.
- O front usa caminhos relativos: `fetch("/api/leiloes")` e `new WebSocket(`ws://${location.host}/ws`)`.
  Nada de IP ou porta fixos, e por isso não existe CORS para configurar.
- A API escuta na porta definida pela variável `PORT` (8028 dentro do contêiner).

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

## Recriar o ambiente do zero (RNF03)

```bash
cp .env.example .env     # preencher DB_PASSWORD e as credenciais do armazenamento
docker compose up -d --build
```

Pré-requisito: Docker com o plugin Compose (`sudo apt-get install -y docker.io docker-compose-v2`).

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
| RNF01 – como os componentes estão organizados na VM | Docker Compose: proxy Caddy (única porta pública), api, db (Postgres), worker | Uma origem só: sem CORS e um único ponto de entrada |
| RF13 – limite de frequência de lances (Nível 2) | | |
| RF21 – busca (grafias, apresentação) (Nível 2) | | |
| RF23 – edição/cancelamento (Nível 2) | | |

# Go Horses — frontend (Vite + React)

Leilão online em tempo real. Visual herdado do [secomp-web-xiv](https://github.com/secompufscar/secomp-web-xiv)
(tema terminal verde/preto, Roboto Mono + Big Shoulders Display + Glacial Indifference), em Vite + React 18,
React Router 6 e Tailwind 3.

## Rodando

```sh
cp env.example .env.local     # opcional; o padrão já funciona com o back-end em :8088
npm install
npm run dev                   # http://localhost:8080
```

Em dev, `/api` (REST e WebSocket) passa pelo proxy do Vite para `VITE_PROXY_TARGET` (padrão `http://127.0.0.1:8088`).
Em produção (`npm run build`), sirva `dist/` e faça o proxy reverso de `/api`, `/uploads` e `/static` para o back-end;
as rotas do front precisam de fallback para `index.html` (Caddy: `try_files {path} /index.html`).
Deixe `VITE_API_URL` vazio no build da VM: o Caddy entrega front e API na mesma origem.

## Estrutura

```
src/
  main.jsx, App.jsx        rotas
  pages/                   Home, Login, Cadastro, NovoLeilao, Detalhe, Sala, Participacoes, MeusLeiloes
  components/              Nav, Button, ui, AuctionCard, Gallery, Countdown, Footer
  lib/                     api.js (único ponto de contato com o back-end), auth.jsx, useRoom.js, clock.js
  utils/                   format.js (dinheiro, datas, estados), alerts.js
```

## Requisitos cobertos

| Requisito | Onde |
|---|---|
| RF01 cadastro/login · RF02 sessão que expira (401 encerra a sessão) | `Cadastro`, `Login`, `lib/auth.jsx`, `lib/api.js` |
| RF04 listagem pública, sala exige login, comitente não dá lance | `useRequireAuth`, `Sala` |
| RF05–RF07 criar leilão, ≥3 fotos, upload direto à nuvem | `NovoLeilao`, `uploadPhoto` |
| RF08 cancelar (Agendado, ou Em andamento sem lances) | `canCancel` em `utils/format.js` |
| RF09 sala ao vivo sem recarregar | `lib/useRoom.js` (WebSocket) |
| RF10 motivo + lance mínimo em toda recusa | `Sala` |
| RF12 reenvio idempotente | `Idempotency-Key` por tentativa/valor |
| RF14 lance mínimo só do servidor | a tela só exibe `min_bid` |
| RF16 relógio do servidor | `serverNow()`; a contagem é só visual |
| RF19 dinheiro e fuso | centavos inteiros; UTC exibido no fuso local |
| RF20/RF21 listagem + busca por nome, categoria e estado | `Home` |
| RF24 reconexão · RF25 espectador · RF26 lance superado · RF27 participações | `useRoom`, `Sala`, `Participacoes` |

Fora desta entrega: RF22 (perfil público), RF23 (edição), RF28 (relistagem) e o Bônus (RF29–RF32).
O backend em `../backend` já implementa o perfil público e a pontuação/crédito; falta só a tela.

## Contrato de API assumido

Ajuste só `src/lib/api.js` (caminhos/formatos) e `src/utils/format.js` (códigos de estado) se o back-end for diferente.
Dinheiro em **centavos inteiros**; horários em **RFC 3339 UTC**; `Authorization: Bearer <token>`.

```
POST /auth/register   {display_name,email,password}             -> 201 (409 se o e-mail já existe)
POST /auth/login      {email,password}                          -> {token,user:{id,display_name,email}}
POST /auth/logout · GET /auth/me
GET  /categories                                                -> ["Eletrônicos", ...]
GET  /auctions?q&category&status&page                           -> {items:[Auction],has_more,server_time}
GET  /auctions/:id                                              -> Auction
POST /auctions        {name,description,category,photos:[url],starting_price,starts_at,duration_seconds}
POST /auctions/:id/cancel
GET  /auctions/:id/room                                         -> {auction,recent_bids,participants,spectators,server_time}
POST /auctions/:id/bids {amount}  + Idempotency-Key             -> 201 {bid,auction}
                                  erro -> {error:{code,message,min_bid}}
GET  /me/auctions · GET /me/participations                      -> [{auction,situation:"leader|outbid|won",my_top_bid}]
POST /uploads/presign {filename,content_type,size}              -> {upload_url,public_url}   (o cliente faz PUT)
WS   /auctions/:id/ws?role=participant|spectator                -> {auction?,recent_bids?,bid?,participants?,spectators?}
     (1ª mensagem do cliente: {"type":"auth","token":"..."}; o token não vai na URL)

Auction = {id,name,description,category,photos:[url],seller:{id,display_name},
           status:"scheduled|running|sold|unsold|cancelled",starting_price,current_price,min_bid,
           bid_count,leader:{id,display_name},winner?,final_price?,starts_at,ends_at}
```

## Decisões da equipe (seção 8 do documento)

- **Tempo real:** WebSocket com reconexão exponencial (1–8 s) e ressincronização por GET ao reconectar.
- **Líder sem expor o nome:** primeiro nome + inicial do sobrenome (`maskName`), aplicado também no cliente.
- **Últimos lances:** 10 na tela.
- **Fotos:** JPG/PNG/WebP, até 5 MB, 3 a 10 por leilão (`VITE_*`); o servidor valida de novo.
- **Listagem:** padrão mostra Agendados e Em andamento, atualiza a cada 10 s, "Carregar mais" paginado.
- **Sessão:** token em `localStorage`; qualquer 401 encerra a sessão e leva ao login, voltando à página de origem.

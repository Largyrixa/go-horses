# Go Horses – projeto de treino (FastAPI + React + Vercel)

Uma lista de tarefas simples com **API em FastAPI** e **front em React (Vite)**.
O objetivo não é o app em si, e sim ensaiar o fluxo completo do hackathon:
criar → rodar local → integrar front e back → publicar → trabalhar em time com Git.

```
gohorses-treino/
├── backend/    API em FastAPI (Python)
└── frontend/   Interface em React + Vite (JavaScript)
```

## Pré-requisitos

- Python 3.9+ e `pip`
- Node.js 18+ e `npm`
- Git e conta no GitHub
- Conta na Vercel e na Render (podem entrar com o GitHub)

---

## Parte 1 – Rodar o back-end (10 min)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Abra http://localhost:8000/docs. O FastAPI gera uma página para testar cada rota.
Teste `GET /tarefas` e `POST /tarefas` por ali antes de mexer no front.

Rotas:

| Método | Rota             | O que faz                         |
|--------|------------------|-----------------------------------|
| GET    | `/tarefas`       | lista as tarefas                  |
| POST   | `/tarefas`       | cria (`{"titulo": "..."}`)        |
| PATCH  | `/tarefas/{id}`  | atualiza `titulo` e/ou `concluida`|
| DELETE | `/tarefas/{id}`  | remove                            |

## Parte 2 – Rodar o front-end (10 min)

Em **outro terminal**, com a API ainda rodando:

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

Abra http://localhost:5173. Adicione, marque e remova tarefas.
Se aparecer "Não consegui falar com a API", veja a seção de problemas comuns.

## Parte 3 – Entender o código (30 min)

Leia nesta ordem, com o app aberto ao lado:

1. `frontend/src/Tarefa.jsx` – um **componente** com **props** (o menor exemplo).
2. `frontend/src/App.jsx` – **estado** (`useState`), busca inicial (`useEffect` + `fetch`),
   e como cada ação chama a API e atualiza o estado.
3. `backend/main.py` – como o FastAPI recebe JSON, valida e responde, e por que existe o CORS.

Regra de ouro do React: **nunca modifique o estado direto**. Crie uma cópia
(`[...tarefas, nova]`, `tarefas.map(...)`, `tarefas.filter(...)`) e passe para o `setTarefas`.

## Parte 4 – Git em time (20 min, os três juntos)

1. Uma pessoa cria o repositório no GitHub e sobe este projeto.
2. As outras clonam (`git clone ...`).
3. Cada um cria uma branch (`git checkout -b minha-feature`), faz uma mudança pequena e abre um Pull Request.
4. Provoquem um conflito de propósito (dois mexendo na mesma linha de `App.css`) e resolvam juntos.
   É melhor errar aqui do que no sábado.

## Parte 5 – Publicar (30–40 min)

A ordem importa: primeiro a API, depois o front, depois o CORS.

### 5.1 API na Render

1. Em render.com: **New → Web Service**, conecte o repositório.
2. **Root Directory:** `backend`
3. **Build Command:** `pip install -r requirements.txt`
4. **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Plano gratuito. Anote a URL gerada (ex.: `https://gohorses-api.onrender.com`).
   Atenção: no plano gratuito a API "dorme" após um tempo sem uso e a primeira
   requisição pode demorar cerca de um minuto. Abra a URL uns minutos antes de uma demo.

### 5.2 Front na Vercel

1. Em vercel.com: **Add New → Project**, importe o mesmo repositório.
2. **Root Directory:** `frontend` (a Vercel detecta Vite sozinha).
3. Em **Environment Variables**, crie `VITE_API_URL` com a URL da API da Render (sem `/` no final).
4. **Deploy.** Anote a URL (ex.: `https://gohorses-treino.vercel.app`).

### 5.3 Liberar o CORS

Na Render, em **Environment**, crie `CORS_ORIGINS` com a URL do front na Vercel
e faça um novo deploy da API. Sem isso o navegador bloqueia as chamadas.

Pronto: a cada `git push` na branch principal a Vercel e a Render publicam de novo sozinhas.

---

## Problemas comuns

- **"Não consegui falar com a API"** – a API está rodando? Abra o DevTools (F12) → aba
  Console. Mensagem com "CORS" quer dizer que falta configurar `CORS_ORIGINS`.
- **Front na Vercel chama `localhost`** – faltou a variável `VITE_API_URL`. Cadastre e
  faça **Redeploy**: variáveis do Vite são lidas na hora do build.
- **Deu 404 ou tela em branco na Vercel** – confira se o *Root Directory* é `frontend`.
- **Primeira chamada na Render demora muito** – é a API acordando (plano gratuito).
- **Os dados somem** – a lista fica em memória e zera quando a API reinicia. É proposital
  para simplificar. Se precisar persistir no hackathon, o caminho mais curto é SQLite.

## Desafios extras (se sobrar tempo)

1. Campo de **prioridade** (alta, média, baixa) na tarefa: mude a API e o front.
2. **Filtro** "todas / pendentes / concluídas" só no front.
3. Persistir com **SQLite** no back-end.
4. Chamar uma **API externa** (por exemplo, uma de IA) a partir da API e exibir o resultado.
5. Trocar o visual usando uma biblioteca de componentes (Bootstrap ou Tailwind).

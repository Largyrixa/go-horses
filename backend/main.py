"""
API de treino para o hackathon: lista de tarefas em memória.

Rodar local:
    pip install -r requirements.txt
    uvicorn main:app --reload

Documentação interativa (gerada sozinha pelo FastAPI): http://localhost:8000/docs
"""
import os
import random
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Go Horses - treino")

# CORS: sem isso o navegador bloqueia o front (outra origem) de chamar a API.
# Em produção, defina CORS_ORIGINS com a URL do front na Vercel, separando por vírgula.
# Exemplo: CORS_ORIGINS=https://meu-app.vercel.app
origens = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in origens],
    allow_methods=["*"],
    allow_headers=["*"],
)


class TarefaNova(BaseModel):
    titulo: str


class TarefaAtualiza(BaseModel):
    titulo: Optional[str] = None
    concluida: Optional[bool] = None

MOTD = [
    "Três pratos de trigo para três tigres tristes",
    "Bosta Bosta Bosta",
    "Silêncio",
    "Eu gosto de inovar",
]

# "Banco de dados" em memória: some quando o servidor reinicia.
# Num hackathon isso costuma bastar; se precisar persistir, troque por SQLite.
tarefas = [
    {"id": 1, "titulo": "Ler o regulamento do hackathon", "concluida": True},
    {"id": 2, "titulo": "Publicar o front na Vercel", "concluida": False},
]
proximo_id = 3


@app.get("/")
def saude():
    """Rota simples para checar se a API está no ar."""
    return {"status": "ok"}


@app.get("/tarefas")
def listar_tarefas():
    return tarefas


@app.post("/tarefas", status_code=201)
def criar_tarefa(dados: TarefaNova):
    global proximo_id
    titulo = dados.titulo.strip()
    if not titulo:
        raise HTTPException(status_code=422, detail="O título não pode ser vazio")
    tarefa = {"id": proximo_id, "titulo": titulo, "concluida": False}
    proximo_id += 1
    tarefas.append(tarefa)
    return tarefa


@app.patch("/tarefas/{tarefa_id}")
def atualizar_tarefa(tarefa_id: int, dados: TarefaAtualiza):
    for tarefa in tarefas:
        if tarefa["id"] == tarefa_id:
            if dados.titulo is not None:
                tarefa["titulo"] = dados.titulo.strip()
            if dados.concluida is not None:
                tarefa["concluida"] = dados.concluida
            return tarefa
    raise HTTPException(status_code=404, detail="Tarefa não encontrada")


@app.delete("/tarefas/{tarefa_id}", status_code=204)
def remover_tarefa(tarefa_id: int):
    for i, tarefa in enumerate(tarefas):
        if tarefa["id"] == tarefa_id:
            tarefas.pop(i)
            return
    raise HTTPException(status_code=404, detail="Tarefa não encontrada")

@app.get("/motd")
def motd():
    return {"texto": random.choice(MOTD)}

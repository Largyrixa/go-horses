# Imagem do backend (FastAPI). A porta vem de $PORT (8088 no docker-compose).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8088
EXPOSE 8088

# 0.0.0.0 é obrigatório para o contêiner aceitar conexões de fora dele.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8088}"]

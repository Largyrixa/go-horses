FROM python:3.12-slim

# Evita arquivos .pyc e garante logs em tempo real no docker logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Instala as dependências (aiomysql, cryptography, fastapi, uvicorn, passlib, etc.)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o código da aplicação
COPY main.py .

# Documenta a porta usada pelo container
EXPOSE 8088

# Inicia o Uvicorn aceitando conexões externas na porta 8088
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8088"]
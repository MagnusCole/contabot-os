# ContaBot — Imagen Docker
# Imagen ligera basada en Python 3.11

FROM python:3.11-slim

WORKDIR /app

# Dependencias del sistema (para Pillow)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libjpeg62-turbo-dev \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Instalar dependencias de Python
COPY pyproject.toml .
COPY contabot/ contabot/
RUN pip install --no-cache-dir .

# Crear directorio de datos
RUN mkdir -p data/db

# Puerto del servidor
EXPOSE 8000

CMD ["uvicorn", "contabot.bot.server:app", "--host", "0.0.0.0", "--port", "8000"]

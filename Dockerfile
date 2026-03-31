FROM python:3.11-slim

WORKDIR /app

# Instalar dependencias del sistema:
# - fuentes para Pillow
# - ffmpeg para MoviePy (codificación de video)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        fonts-dejavu-core \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Instalar dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar resto del proyecto
COPY . .

RUN mkdir -p /app/static/uploads /app/static/videos

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

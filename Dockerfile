FROM python:3.11-slim

WORKDIR /app

# Instalar dependencias del sistema:
# - fuentes para Pillow y Remotion
# - Chromium headless para Remotion
# - ffmpeg para codificar video
# - Node.js 20 para Remotion
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        fonts-dejavu-core \
        chromium \
        ffmpeg \
        curl \
        gnupg \
        dbus \
        libnss3 \
        libatk-bridge2.0-0 \
        libdrm2 \
        libxcomposite1 \
        libxdamage1 \
        libxrandr2 \
        libgbm1 \
        libasound2 \
        libpangocairo-1.0-0 \
        libgtk-3-0 \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Variables para que Remotion encuentre Chromium
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium
ENV REMOTION_CHROME_EXECUTABLE=/usr/bin/chromium
ENV CHROMIUM_FLAGS="--no-sandbox --disable-gpu --disable-dev-shm-usage"

# Instalar dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Instalar dependencias de Remotion (video/)
COPY video/package.json video/package-lock.json* video/
RUN cd video && npm install --legacy-peer-deps

# Copiar resto del proyecto
COPY . .

RUN mkdir -p /app/static/uploads /app/static/videos

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

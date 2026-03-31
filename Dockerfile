FROM python:3.11-slim

WORKDIR /app

# Instalar dependencias del sistema: fuentes, Node.js 20, Chromium para Remotion
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        fonts-dejavu-core \
        chromium \
        curl \
        gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Variable para que Remotion encuentre Chromium
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium
ENV REMOTION_CHROME_EXECUTABLE=/usr/bin/chromium

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

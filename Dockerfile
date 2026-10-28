FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund

FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libgomp1 libxrender1 libxt6 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements-cad.txt ./
RUN pip install --no-cache-dir -r requirements-cad.txt
COPY --from=frontend /build/node_modules/three /app/node_modules/three
COPY server.py engine.py geometry.py models.py ai_provider.py step_import.py cad_inspect.py ./
COPY static ./static
RUN useradd --uid 10001 --create-home form && mkdir /app/.data && chown form:form /app/.data
USER form
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=3)"
CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8000"]

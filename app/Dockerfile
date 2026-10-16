FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends libreoffice-writer fonts-liberation fonts-crosextra-carlito && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt VERSION .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py documents.py invoice_mail.py booking_import.py email_templates.py microsoft_graph.py connect_microsoft.py bootstrap.py ./
COPY tests ./tests
COPY templates ./templates
COPY static ./static
ENV DATA_DIR=/data PORT=8080 PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)"
CMD ["python", "bootstrap.py"]

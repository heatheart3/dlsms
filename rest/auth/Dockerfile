FROM python:3.9-slim

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

EXPOSE 8081

CMD ["gunicorn", "--bind", "0.0.0.0:8081", "--workers", "4", "--timeout", "120", "app:app"]

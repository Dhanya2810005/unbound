FROM python:3.13-slim

WORKDIR /app

# System deps (minimal)
RUN pip install --no-cache-dir --upgrade pip

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

ENV PYTHONUNBUFFERED=1

# Cloud Run injects PORT at runtime (typically 8080). Keep 8000 as a local default.
ENV PORT=8000

EXPOSE 8000

CMD ["sh", "-c", "python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

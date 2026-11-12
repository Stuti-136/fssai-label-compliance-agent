FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HF_HOME=/models
WORKDIR /app
# CPU-only torch keeps the image small (sentence-transformers needs it)
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
RUN useradd -m app && mkdir -p /data /models && chown -R app /data /models /app
USER app
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.12-slim
WORKDIR /workspace
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/workspace/src:/workspace
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src ./src
COPY app ./app
EXPOSE 8787
CMD ["uvicorn", "app.service:app", "--host", "0.0.0.0", "--port", "8787"]


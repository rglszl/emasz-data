FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 TZ=Europe/Budapest
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY ha_import.py .
CMD ["python", "ha_import.py", "--daemon"]

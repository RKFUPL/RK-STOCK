FROM python:3.12-slim

WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY backend/ .
EXPOSE 5006

CMD ["gunicorn", "--bind", "0.0.0.0:5006", "--workers", "2", "run:app"]

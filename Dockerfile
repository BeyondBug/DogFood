FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt /app/requirements.txt
COPY vendor/wheels /wheels
RUN python -m pip install --no-index --find-links=/wheels -r /app/requirements.txt \
    && rm -rf /wheels

COPY src /app/src
COPY fixtures.json /app/fixtures.json

EXPOSE 8080
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080"]

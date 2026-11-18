# La app solo usa la biblioteca estándar de Python: no hay nada que instalar.
FROM python:3.13-alpine

WORKDIR /app
COPY app/ .

ENV PUERTO=8080 \
    PYTHONDONTWRITEBYTECODE=1
EXPOSE 8080

# No correr como root (el UID numérico permite usar runAsNonRoot en Kubernetes).
USER 10001

CMD ["python", "server.py"]

FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt pyproject.toml ./
COPY src ./src
COPY tools ./tools
RUN pip install --no-cache-dir .
ENV PYTHONPATH=/app/src
CMD ["gunicorn", "--bind", "0.0.0.0:8211", "--workers", "2", "quantum_randomness_service.app:app"]
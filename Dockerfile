FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt pyproject.toml ./
COPY README.md LICENSE ./
COPY docs ./docs
COPY src ./src
COPY tools ./tools
RUN pip install --no-cache-dir .
ENV PYTHONPATH=/app/src
ENV SETUP_GUIDE_PATH=/app/docs/randomness-service.md
CMD ["python", "tools/run_randomness_machine.py"]
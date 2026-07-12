FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY integrations/apex_swe/tasks/frontier-incident-smoke ./integrations/apex_swe/tasks/frontier-incident-smoke

RUN pip install --no-cache-dir -e ".[adapters]"

ENV PYTHONPATH=/app/src
CMD ["python", "/app/integrations/apex_swe/tasks/frontier-incident-smoke/scripted_agent.py"]

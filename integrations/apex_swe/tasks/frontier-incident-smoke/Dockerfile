FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY ./src/agent_surface ./src/agent_surface
COPY ./src/event_service_substrate ./src/event_service_substrate
COPY ./src/integrations ./src/integrations
COPY ./src/training_adapters ./src/training_adapters
COPY ./src/training_ground ./src/training_ground
COPY integrations/apex_swe/tasks/frontier-incident-smoke ./integrations/apex_swe/tasks/frontier-incident-smoke

RUN pip install --no-cache-dir -e ".[adapters]"

ENV PYTHONPATH=/app/src
CMD ["python", "/app/integrations/apex_swe/tasks/frontier-incident-smoke/scripted_agent.py"]

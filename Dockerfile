FROM python:3.12-slim AS base
WORKDIR /code

RUN apt-get update && apt-get install -y libpango-1.0-0 libharfbuzz0b libpangoft2-1.0-0 libharfbuzz-subset0

COPY ./requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt
COPY ./backend /code/backend
COPY ./tools /code/tools
RUN chown -R 1000 /code
USER 1000
EXPOSE 9090
RUN python -m tools.seed_db
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "9090"]

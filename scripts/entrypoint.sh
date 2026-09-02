#!/bin/sh
set -eu

echo "Running database migrations"
alembic upgrade head

echo "Seeding demo data if needed"
python -m app.seed

echo "Starting TacTech API"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000

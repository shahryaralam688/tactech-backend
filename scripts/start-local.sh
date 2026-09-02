#!/bin/sh
set -eu

cd "$(dirname "$0")/.."

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew required. Install from https://brew.sh"
  exit 1
fi

if [ ! -f .env ]; then
  cp .env.example .env
  jwt="$(openssl rand -base64 48 | tr -d '\n')"
  dbpass="$(openssl rand -hex 16)"
  tmp="$(mktemp)"
  sed \
    -e "s|JWT_SECRET=replace-with-a-long-random-secret|JWT_SECRET=${jwt}|" \
    -e "s|POSTGRES_PASSWORD=change_me|POSTGRES_PASSWORD=${dbpass}|" \
    -e "s|DATABASE_URL=postgresql+psycopg2://tactech:change_me@localhost:5432/tactech|DATABASE_URL=postgresql+psycopg2://tactech:${dbpass}@localhost:5432/tactech|" \
    .env > "$tmp"
  mv "$tmp" .env
  echo "Created .env with generated secrets"
fi

# shellcheck disable=SC1091
POSTGRES_PASSWORD="$(awk -F= '/^POSTGRES_PASSWORD=/{print $2; exit}' .env)"

if ! command -v psql >/dev/null 2>&1; then
  echo "Installing PostgreSQL 16..."
  brew install postgresql@16
fi
if ! command -v redis-server >/dev/null 2>&1; then
  echo "Installing Redis..."
  brew install redis
fi

brew services start postgresql@16 >/dev/null 2>&1 || brew services start postgresql >/dev/null 2>&1 || true
brew services start redis >/dev/null 2>&1 || true

export PATH="/opt/homebrew/opt/postgresql@16/bin:/usr/local/opt/postgresql@16/bin:$PATH"

echo "Waiting for Postgres..."
i=0
while ! psql postgres -c "SELECT 1" >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -gt 30 ]; then
    echo "Postgres did not start. Run: brew services start postgresql@16"
    exit 1
  fi
  sleep 1
done

psql postgres -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'tactech') THEN
    CREATE ROLE tactech LOGIN PASSWORD '${POSTGRES_PASSWORD}';
  ELSE
    ALTER ROLE tactech WITH LOGIN PASSWORD '${POSTGRES_PASSWORD}';
  END IF;
END
\$\$;
SQL

if ! psql -lqt | cut -d \| -f 1 | grep -qw tactech; then
  createdb -O tactech tactech
fi

if ! command -v python3.12 >/dev/null 2>&1; then
  echo "Installing Python 3.12 (3.14 cannot install this project)..."
  brew install python@3.12
  export PATH="/opt/homebrew/opt/python@3.12/bin:/usr/local/opt/python@3.12/bin:$PATH"
fi

if [ -d .venv ] && ! .venv/bin/python -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)' >/dev/null 2>&1; then
  echo "Removing incompatible virtualenv..."
  rm -rf .venv
fi

if [ ! -d .venv ]; then
  python3.12 -m venv .venv
fi

.venv/bin/pip install -q -r requirements.txt

echo "Migrating and seeding..."
.venv/bin/alembic upgrade head
.venv/bin/python -m app.seed

echo
echo "API:   http://localhost:8000"
echo "Ngrok: ngrok http 8000"
echo "App:   use the https://xxxx.ngrok-free.app URL"
echo
exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000

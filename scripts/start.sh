#!/bin/sh
set -eu

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  cp .env.example .env
  jwt="$(openssl rand -base64 48 | tr -d '\n')"
  dbpass="$(openssl rand -base64 24 | tr -d '\n=/+')"
  tmp="$(mktemp)"
  sed \
    -e "s|JWT_SECRET=replace-with-a-long-random-secret|JWT_SECRET=${jwt}|" \
    -e "s|POSTGRES_PASSWORD=change_me|POSTGRES_PASSWORD=${dbpass}|" \
    -e "s|DATABASE_URL=postgresql+psycopg2://tactech:change_me@localhost:5432/tactech|DATABASE_URL=postgresql+psycopg2://tactech:${dbpass}@localhost:5432/tactech|" \
    .env > "$tmp"
  mv "$tmp" .env
  echo "Created .env with generated secrets"
fi

echo "Starting API on http://localhost:8000"
echo "Then run: ngrok http 8000"
echo "Use the https://....ngrok-free.app URL in the iOS app"
exec docker compose up --build

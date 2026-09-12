.PHONY: up down logs migrate revision lint test

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f core

migrate:
	docker compose exec core alembic upgrade head

revision:
	docker compose exec core alembic revision -m "$(m)"

lint:
	ruff check core

test:
	pytest

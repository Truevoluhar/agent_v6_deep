SHELL := /bin/bash

.PHONY: up down build logs test verify

up:
	docker compose up -d --build

down:
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f --tail=200

test:
	pytest -q

verify:
	python -m compileall agent_api workspace_api client tests


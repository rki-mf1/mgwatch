.PHONY: test lint format check

test:
	./scripts/dev-manage.sh test

lint:
	pre-commit run --all-files

format:
	pre-commit run ruff-format --all-files
	pre-commit run djlint-reformat-django --all-files

check:
	./scripts/dev-manage.sh check

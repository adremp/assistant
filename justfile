# Run the bot
run:
	fastapi dev main.py

# Install dependencies
install:
	uv sync

# Run Redis
redis:
	docker run -d -p 6379:6379 redis:alpine

# Type check
typecheck:
	uv run mypy app/

# Format code
format:
	uv run ruff format app/

# Lint code
lint:
	uv run ruff check app/

# Run tests
test:
	uv run pytest tests/ -v

# Clean cache
clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type d -name .mypy_cache -exec rm -rf {} +
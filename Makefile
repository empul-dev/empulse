.PHONY: lint fix test dev

# Run linters
lint:
	ruff check empulse/
	ruff format --check empulse/

# Auto-fix all lint errors in changed files
fix:
	claude -p "Fix all lint errors in changed files (git diff --name-only HEAD~1). Run ruff check and ruff format for Python. Show me what changed." --allowedTools "Edit,Read,Bash,Grep"

# Run tests
test:
	pytest tests/

# Run dev server
dev:
	uvicorn empulse.app:create_app --factory --reload --port 8189

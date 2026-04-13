# Python Code Style

- Python 3.11+ features allowed
- Use type hints for all function parameters and return types
- Use Pydantic for data validation (BaseModel, not dataclass)
- Use async/await for all I/O operations in API layer
- Imports order: stdlib → third-party → local (enforced by ruff)
- Use `pathlib.Path` instead of `os.path`
- String formatting: f-strings preferred
- Maximum line length: 120 characters
- Use `logging` module, never `print()` in production code
- Constants in UPPER_SNAKE_CASE
- Environment variables loaded via pydantic-settings
- Linter/Formatter: ruff
- Type checker: mypy

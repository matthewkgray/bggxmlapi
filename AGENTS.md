# Agent Instructions for bgg-api project

This document provides guidance for developing the `bgg-api` Python library.

## Project Structure

- `bgg_api/`: The main package source code.
  - `client.py`: Contains the main `BGGClient`.
  - `models.py`: Contains the data classes (`Game`, `User`, etc.).
  - `exceptions.py`: Contains custom exceptions.
- `tests/`: Contains all unit and integration tests.
- `pyproject.toml`: Project definition and dependencies.

## Development Workflow

1.  **Dependencies**: Install dependencies using `pip install -e .[dev]`.
2.  **TDD**: When adding a new feature, start by writing a failing test.
3.  **API Endpoints**: The BGG XML API2 documentation can be found online. Be mindful of their rate limiting. The client should handle this gracefully.
4.  **Data Parsing**: Use the `lxml` library for parsing XML responses. It is more feature-rich and performant than the standard library `xml.etree.ElementTree`.
5.  **Coding Style**: Follow PEP 8 guidelines. Use `black` for code formatting.

## Key Design Decisions

- **Lazy Loading**: `Game` and `User` objects should load their detailed data lazily upon attribute access to avoid unnecessary API calls.
- **Caching**: All requests to the BGG API should be cached to improve performance and respect rate limits. `requests-cache` is configured for this.
- **Pagination**: The `Ratings` class must handle fetching paginated rating data transparently.

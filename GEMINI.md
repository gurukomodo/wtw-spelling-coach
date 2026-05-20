# Project Rules & Context (WTW Spelling Coach)

## Tech Stack & Architecture
- Framework: Streamlit UI
- Database: SQLite (`database_manager.py`)
- Core Entry Point: `app.py`

## Active Refactoring Plan (Execute Phase by Phase)

## Current Refactoring Goals
- Target 1: Eliminate duplicate G-Level metadata by routing everything to a central constants.py file.
- Target 2: Standardize SQLite connections using a context manager in database_manager.py to prevent boilerplate leaks.
- Target 3: Keep functions single-purpose; do not blend Streamlit UI rendering with deep scoring mathematics.

### Phase 2: Database Boilerplate Cleanup
- Target: Standardize SQLite connections using a context manager in `database_manager.py` to prevent connection leaks.

### Phase 3: Monolith Decomposition
- Target: Break down `app.py` by moving isolated UI features into a `components/` directory.

## Agent Constraints
- Keep code simple, explicit, and easy to maintain.
- Do NOT rewrite entire files if you are only fixing a small bug or updating imports.
- Prioritize backwards compatibility; do not change any application behavior or routing logic unless specifically asked.
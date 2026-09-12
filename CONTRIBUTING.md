# Contributing to the Invoice Intelligence Platform

We appreciate your interest in contributing! Following these guidelines helps ensure a smooth, high-quality development process.

## Branching Strategy

We follow a feature-branching model:
- `main` is the stable, production-ready branch.
- Feature branches should be branched off `main` and named descriptively (e.g., `feature/snowflake-etl`, `fix/blob-extension-bug`).
- Open a Pull Request (PR) against `main` for review.

## Code Quality Standards

The project relies on strict linting and type checking enforced by GitHub Actions. Before submitting a PR, ensure your code passes all local checks:

1. **Linting (Ruff):**
   We use [Ruff](https://beta.ruff.rs/docs/) as our linter and formatter.
   ```bash
   ruff check backend/
   ```
   To auto-fix fixable issues:
   ```bash
   ruff check --fix backend/
   ```

2. **Static Type Checking (Mypy):**
   We use [Mypy](https://mypy.readthedocs.io/) for strict type enforcement.
   ```bash
   python -m mypy backend/src
   ```
   Ensure you provide complete type annotations for all new functions and variables. If a third-party library lacks stubs, use `# type: ignore[import-untyped]`.

3. **Testing (Pytest):**
   Ensure all unit tests pass and write new tests for your features.
   ```bash
   pytest backend/tests/
   ```

## Pull Request Process

1. Ensure your PR description clearly details the problem being solved and the approach taken.
2. The GitHub Actions CI pipeline must pass (Linting, Typing, and Build checks).
3. If your changes affect the architecture or the deployment process, update the respective documentation in the `docs/` folder.
4. Two approvals from maintainers are required before merging.

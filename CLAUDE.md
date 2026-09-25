# Jarvis project notes

- This is my Jarvis project. Make small, explained changes.
  Don't delete files or push to GitHub unless I explicitly ask.
- CLI: `poetry run python main.py`
- Web dashboard: `poetry run python main.py --server`
  - Opens at http://localhost:8000/login
- Tests: `poetry run pytest`
- `.env` contains secrets. Never display, copy, or change its contents.
- Brain integration uses `BRAIN_ENABLED` and `BRAIN_PATH`.
  Brain notes live in `C:\Users\NathanGrainger\mi-aios`.
- The separate 3D brain viewer is in
  `C:\Users\NathanGrainger\mi-aios\apps\3d-brain`, served on port 4640.
  It is only a viewer; Jarvis reads the notes directly and doesn't need it.
- Before editing, explain the plan. After editing, summarize files changed and tests run.

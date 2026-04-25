# Sentinel

Prototype scaffold for Sentinel cloud service and shared contracts.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
pytest
uvicorn cloud.app:app --reload
```

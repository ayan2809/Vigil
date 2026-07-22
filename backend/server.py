"""Vigil local FastAPI server launcher."""

from __future__ import annotations

import sys
from pathlib import Path

# Add backend directory to sys.path if launched directly
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import uvicorn
from vigil.main import app

if __name__ == "__main__":
    uvicorn.run("vigil.main:app", host="127.0.0.1", port=8200, reload=False)

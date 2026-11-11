import os
import sys

import pytest

# Make the project root importable when running pytest from any folder
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app as flask_app  # noqa: E402
from database.db import init_db  # noqa: E402


@pytest.fixture
def app(tmp_path):
    # Every test gets its own empty database, never the real skin_index.db
    db = str(tmp_path / "test.db")
    init_db(db)
    flask_app.config.update(TESTING=True, DATABASE=db)
    return flask_app

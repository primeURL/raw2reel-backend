import pytest


@pytest.fixture(autouse=True)
def _offline_sound_library():
    """Tests never read the real library in R2: start every test with an empty one."""
    from app.services import library

    library.set_manifest({"version": 1, "music": [], "sfx": []})
    yield

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_user_config(tmp_path: Path, monkeypatch) -> None:
    """Never read or write the developer's real repository registry in tests."""

    home = tmp_path / "user-home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

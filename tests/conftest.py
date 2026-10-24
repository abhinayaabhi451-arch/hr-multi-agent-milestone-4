import copy
import pytest

import memory.long_term as lt
from tools import mock_data


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Each test gets a throwaway knowledge store and pristine mock data."""
    monkeypatch.setattr(lt, "_STORE_PATH", str(tmp_path / "store.json"))
    monkeypatch.setattr(lt, "_cache", None)
    monkeypatch.setattr(lt, "_cache_mtime", None)
    saved = (copy.deepcopy(mock_data.EMPLOYEES), copy.deepcopy(mock_data.LEAVE_BALANCES))
    yield
    mock_data.EMPLOYEES.clear(); mock_data.EMPLOYEES.update(saved[0])
    mock_data.LEAVE_BALANCES.clear(); mock_data.LEAVE_BALANCES.update(saved[1])

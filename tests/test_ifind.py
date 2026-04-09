import pytest
from unittest.mock import patch
import pandas as pd
from data.providers.ifind_provider import iFinDDataProvider

@pytest.fixture
def mock_ifind():
    with patch("iFinDPy.ths_login", return_value=0), \
         patch("iFinDPy.ths_logout"), \
         patch("diskcache.Cache") as mock_cache:
        mock_cache_instance = mock_cache.return_value
        mock_cache_instance.get.return_value = None
        yield iFinDDataProvider("u", "p", "./fake.lic")

def test_login_success(mock_ifind): assert mock_ifind._is_logged_in
def test_fetch_ohlcv_empty(mock_ifind):
    with patch("iFinDPy.ths_HistoryQuotes", return_value=(pd.DataFrame(), "Success")):
        df = mock_ifind.fetch_ohlcv("000001.SZ", "D", pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-10"))
        assert df.empty

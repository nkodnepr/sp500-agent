"""Тесты для ticker_validation.py — защита от path traversal и мусорного ввода."""
import pytest

from ticker_validation import sanitize_ticker, is_safe_ticker_format


@pytest.mark.parametrize("ticker", [
    "AAPL", "TSLA", "MSFT", "GOOGL", "BRK-B", "BF.B", "A", "SPY",
])
def test_legitimate_tickers_pass(ticker):
    assert sanitize_ticker(ticker) == ticker.upper()
    assert is_safe_ticker_format(ticker)


@pytest.mark.parametrize("ticker", [
    "../../../etc/passwd",
    "..\\..\\..\\Windows\\System32",
    "..\\..\\AppData\\Roaming\\Startup\\evil",
    "AAPL/../../../etc",
    "AAPL; rm -rf /",
    "AAPL\x00.exe",
    "   ",
    "",
    "A" * 500,
    "AAPL TSLA",  # пробел внутри
    None,
    123,
])
def test_malicious_or_malformed_input_rejected(ticker):
    with pytest.raises(ValueError):
        sanitize_ticker(ticker)
    assert is_safe_ticker_format(ticker) is False


@pytest.mark.parametrize("reserved", ["CON", "con", "PRN", "AUX", "NUL", "COM1", "LPT9"])
def test_windows_reserved_device_names_rejected(reserved):
    """Не уязвимость как таковая, но создание файла/папки с таким именем
    на Windows ведёт себя непредсказуемо — блокируем на всякий случай."""
    with pytest.raises(ValueError):
        sanitize_ticker(reserved)


def test_lowercase_input_normalized_to_uppercase():
    assert sanitize_ticker("aapl") == "AAPL"


def test_whitespace_stripped():
    assert sanitize_ticker("  AAPL  ") == "AAPL"

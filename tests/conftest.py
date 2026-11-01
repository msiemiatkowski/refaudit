import csv
from pathlib import Path

import pytest

from refaudit.lookup import Client

TESTS = Path(__file__).parent
FIXTURES = TESTS / "fixtures"


def offline_client() -> Client:
    """A client that answers only from the API responses recorded in tests/fixtures/http."""
    return Client(FIXTURES / "http", offline=True)


def expected_cases() -> list[dict]:
    with open(TESTS / "expected.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.fixture
def offline() -> Client:
    return offline_client()

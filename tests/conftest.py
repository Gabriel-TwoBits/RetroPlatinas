import pytest


@pytest.fixture
def api_client(client):
    """Cliente HTTP do Django para testes de endpoints. Expandir nos PRs seguintes."""
    return client

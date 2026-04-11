import pytest

from quarry.http import close_client, get_client


@pytest.mark.asyncio
async def test_get_client_returns_singleton():
    client1 = get_client()
    client2 = get_client()
    assert client1 is client2
    await close_client()


@pytest.mark.asyncio
async def test_close_client_resets_singleton():
    client1 = get_client()
    await close_client()
    client2 = get_client()
    assert client1 is not client2
    await close_client()

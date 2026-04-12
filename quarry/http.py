import asyncio

import httpx

_client: httpx.AsyncClient | None = None
_client_loop_id: int | None = None


def get_client() -> httpx.AsyncClient:
    global _client, _client_loop_id
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    current_loop_id = id(loop) if loop is not None else None

    if _client is not None and _client_loop_id != current_loop_id:
        _client = None

    if _client is None:
        _client = httpx.AsyncClient(
            timeout=10.0,
            follow_redirects=True,
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
            ),
            headers={"User-Agent": "Quarry/0.1"},
        )
        _client_loop_id = current_loop_id

    return _client


async def close_client() -> None:
    global _client, _client_loop_id
    if _client is not None:
        await _client.aclose()
        _client = None
        _client_loop_id = None

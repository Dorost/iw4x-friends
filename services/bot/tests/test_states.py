import httpx
import pytest
from fake import BOT_TOKEN

from bot.servers import fetch_states, verify_init_data

SERVERS = ["https://mw2-nl.dorost.nl", "https://mw2-us.dorost.nl"]
URL = "http://127.0.0.1:8070/tg/api/states"


@pytest.mark.anyio
async def test_states_from_the_bastion():
    """With BOT_STATES_URL one call to the control plane, signed as the bot itself."""
    seen = []

    def bastion(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={SERVERS[0]: {"status": "match", "players": ["Amin"]}, SERVERS[1]: None},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(bastion)) as http:
        out = await fetch_states(SERVERS, BOT_TOKEN, 123456, http, states_url=URL)
    assert out == {SERVERS[0]: {"status": "match", "players": ["Amin"]}, SERVERS[1]: None}
    assert [str(r.url) for r in seen] == [URL]
    signed = seen[0].headers["authorization"].removeprefix("tma ")
    assert verify_init_data(BOT_TOKEN, signed)["id"] == 123456


@pytest.mark.anyio
async def test_bastion_not_answering_means_unreachable():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(503))
    ) as http:
        out = await fetch_states(SERVERS, BOT_TOKEN, 123456, http, states_url=URL)
    assert out == dict.fromkeys(SERVERS)

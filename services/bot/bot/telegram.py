"""A thin Telegram Bot API client. Tests use FakeTelegram (tests/fake.py) with the same call()."""

from typing import Any, Protocol

import httpx

API = "https://api.telegram.org"


class TelegramError(Exception):
    def __init__(self, code: int, description: str, parameters: dict | None = None):
        super().__init__(f"{code} {description}")
        self.code, self.description, self.parameters = code, description, parameters or {}


class Client(Protocol):
    async def call(self, method: str, wait: float = 20, **params: Any) -> Any: ...


class Telegram:
    def __init__(self, token: str):
        self._url = f"{API}/bot{token}/"
        self._http = httpx.AsyncClient()

    async def call(self, method: str, wait: float = 20, **params: Any) -> Any:
        try:
            r = await self._http.post(self._url + method, json=params, timeout=wait)
            data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            # str(e) never holds the URL (and with it the token)
            raise TelegramError(0, type(e).__name__) from None
        if not data.get("ok"):
            raise TelegramError(
                data.get("error_code", r.status_code),
                data.get("description", ""),
                data.get("parameters"),
            )
        return data["result"]

    async def close(self) -> None:
        await self._http.aclose()

"""Stateless cookie handling and safe, typed failures for the pinned SDK transport."""

from http.cookiejar import Cookie, CookieJar, DefaultCookiePolicy
from urllib.request import Request

from openai import OpenAIError


class OpenAIRequestPolicyError(OpenAIError):
    """A request violated Fleet's exact transport policy, without retaining payloads."""

    def __init__(self) -> None:
        super().__init__("The provider request failed the pinned transport policy.")


class OpenAIResponsePolicyError(OpenAIError):
    """A response violated Fleet's exact transport policy, without retaining payloads."""

    def __init__(self) -> None:
        super().__init__("The provider response failed the pinned transport policy.")


class _RejectAllCookiePolicy(DefaultCookiePolicy):
    def set_ok(self, cookie: Cookie, request: Request) -> bool:
        return False

    def return_ok(self, cookie: Cookie, request: Request) -> bool:
        return False


def new_stateless_cookie_jar() -> CookieJar:
    """Reject cookies before HTTPX extracts them, independently for every client.

    Pass this jar directly to the HTTP client: wrapping it in HTTPX ``Cookies``
    can copy its entries without preserving this policy. Request header guards
    still reject explicit Cookie headers; a jar policy does not authorize them.
    """

    return CookieJar(policy=_RejectAllCookiePolicy())

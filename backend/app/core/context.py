from __future__ import annotations

from contextvars import ContextVar
from fastapi import Request
from ipaddress import ip_address, ip_network

from app.settings import settings

request_client_id: ContextVar[str | None] = ContextVar("request_client_id", default=None)
request_ip_address: ContextVar[str | None] = ContextVar("request_ip_address", default=None)
request_trace_id: ContextVar[str | None] = ContextVar("request_trace_id", default=None)


def client_ip(request: Request) -> str | None:
    peer = request.client.host if request.client else None
    try:
        trusted = any(ip_address(peer) in ip_network(value.strip()) for value in settings.trusted_proxy_cidrs.split(",") if value.strip())
    except ValueError:
        trusted = False
    forwarded = request.headers.get("X-Real-IP") if trusted else None
    try:
        return str(ip_address(forwarded)) if forwarded else peer
    except ValueError:
        return peer

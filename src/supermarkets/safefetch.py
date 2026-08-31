"""Refuse to fetch things that are not on the public internet.

Anything that takes a URL from a caller and fetches it is a way to reach the
network the server is sitting on. That matters here more than it would on a
public host: this app is built to run on a home NAS behind Tailscale, where
"192.168.1.1" is the router's admin page and "127.0.0.1:8000" is the app
itself. An account shared with a friend should not also be a way to knock on
every door on the owner's LAN.

The check is made against the *resolved* address rather than the hostname,
because a name can point wherever its owner likes, and again after any
redirect, because the first hop is not the only one.
"""

from typing import Iterable
import ipaddress
import socket
import urllib.parse


class Refused(Exception):
    """The URL is not one this will fetch, and why."""


def _addresses(host: str) -> Iterable[ipaddress._BaseAddress]:
    try:
        info = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise Refused(f"That host could not be resolved ({exc}).") from exc
    return {ipaddress.ip_address(item[4][0]) for item in info}


def check_url(url: str, schemes: Iterable[str] = ("https",)) -> str:
    """Return the URL, or raise Refused saying why not."""
    parsed = urllib.parse.urlsplit(url or "")
    if parsed.scheme not in tuple(schemes):
        allowed = " or ".join(sorted(schemes))
        raise Refused(f"Only {allowed} addresses are fetched.")
    if not parsed.hostname:
        raise Refused("That address has no host.")

    for address in _addresses(parsed.hostname):
        if (address.is_private or address.is_loopback or address.is_reserved
                or address.is_link_local or address.is_multicast
                or address.is_unspecified):
            raise Refused(
                "That address is on a private network, so it is not fetched.")
    return url

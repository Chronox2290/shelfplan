"""Fetch a recipe's photograph on the page's behalf.

An imported recipe's picture lives on whatever site it came from, and the
content security policy allows images from this server and the two supermarket
CDNs and nothing else. Widening that to "any https host" would work and would
also mean every recipe page you look at gets told your address by name, which
is a poor trade for a photograph.

Fetching it here keeps the policy as tight as it was: the page only ever asks
this server for images, and the recipe site sees one request from the server
that already fetched the recipe.

Being a fetcher that takes a URL from a caller, this is an SSRF hazard, and it
runs on home networks behind Tailscale where "localhost" and "192.168.x" mean
something. So: https only, public addresses only, checked after resolution
rather than by reading the hostname, with a size cap and a short timeout.
"""

from typing import Dict, Tuple
import time

import requests

from src.supermarkets import safefetch

MAX_BYTES = 4 * 1024 * 1024
TIMEOUT_S = 12
CACHE_SECONDS = 24 * 60 * 60
_CACHE_MAX = 60

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}

# url -> (fetched_at, content_type, body)
_cache: Dict[str, Tuple[float, str, bytes]] = {}


# The address check lives with the recipe importer's, because there is no
# reason for two of them and every reason for one that is tested.
Refused = safefetch.Refused


def _check(url: str) -> str:
    return safefetch.check_url(url, schemes=("https",))


def fetch(url: str) -> Tuple[str, bytes]:
    """The image bytes and their content type, from cache where possible."""
    now = time.time()
    hit = _cache.get(url)
    if hit and now - hit[0] < CACHE_SECONDS:
        return hit[1], hit[2]

    _check(url)
    response = requests.get(url, headers=_HEADERS, timeout=TIMEOUT_S,
                            stream=True, allow_redirects=True)
    # A redirect can land somewhere the first check would have refused.
    _check(response.url)
    response.raise_for_status()

    content_type = (response.headers.get("Content-Type") or "").split(";")[0]
    if not content_type.startswith("image/"):
        raise Refused(f"That URL returned {content_type or 'no content type'}, "
                      "not an image.")

    body = bytearray()
    for chunk in response.iter_content(64 * 1024):
        body.extend(chunk)
        if len(body) > MAX_BYTES:
            raise Refused("That image is larger than 4MB.")

    if len(_cache) >= _CACHE_MAX:
        oldest = min(_cache, key=lambda k: _cache[k][0])
        _cache.pop(oldest, None)
    _cache[url] = (now, content_type, bytes(body))
    return content_type, bytes(body)

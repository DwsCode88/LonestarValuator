"""Shared HTTP session."""
from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
TIMEOUT = 20


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "en-US,en;q=0.9",
    })
    retry = Retry(total=2, backoff_factor=0.8, status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=frozenset(["GET", "POST"]))
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    return s

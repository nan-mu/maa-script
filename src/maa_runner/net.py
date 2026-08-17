from __future__ import annotations

from dataclasses import dataclass

import requests

from maa_runner.config import Config


@dataclass(frozen=True)
class ProbeResult:
    url: str
    ok: bool
    detail: str


def proxy_env(proxy: str) -> dict[str, str]:
    proxy = proxy.strip()
    if not proxy:
        return {}
    return {
        "HTTP_PROXY": proxy,
        "HTTPS_PROXY": proxy,
        "http_proxy": proxy,
        "https_proxy": proxy,
    }


def _proxies(cfg: Config) -> dict[str, str] | None:
    env = proxy_env(cfg.network.proxy)
    if not env:
        return None
    return {"http": env["http_proxy"], "https": env["https_proxy"]}


def probe_url(cfg: Config, url: str) -> ProbeResult:
    try:
        response = requests.get(
            url,
            proxies=_proxies(cfg),
            timeout=cfg.network.probe_timeout_sec,
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        return ProbeResult(url=url, ok=False, detail=str(exc))
    status = response.status_code
    ok = 200 <= status < 400
    return ProbeResult(url=url, ok=ok, detail=str(status))


def probe_all(cfg: Config) -> list[ProbeResult]:
    return [probe_url(cfg, url) for url in cfg.network.probe_urls]

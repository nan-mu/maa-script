from __future__ import annotations

from dataclasses import dataclass

import requests

from maa_runner.config import Config


@dataclass(frozen=True)
class ProbeResult:
    url: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class ProxyAttempt:
    proxy: str  # "" = direct
    results: tuple[ProbeResult, ...]

    @property
    def ok(self) -> bool:
        return bool(self.results) and all(r.ok for r in self.results)

    @property
    def label(self) -> str:
        return self.proxy if self.proxy else "直连"


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


def requests_proxies(proxy: str) -> dict[str, str] | None:
    env = proxy_env(proxy)
    if not env:
        return None
    return {"http": env["http_proxy"], "https": env["https_proxy"]}


def _proxies(cfg: Config) -> dict[str, str] | None:
    return requests_proxies(cfg.network.proxy)


def probe_url(cfg: Config, url: str, *, proxy: str | None = None) -> ProbeResult:
    chosen = cfg.network.proxy if proxy is None else proxy
    try:
        response = requests.get(
            url,
            proxies=requests_proxies(chosen),
            timeout=cfg.network.probe_timeout_sec,
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        return ProbeResult(url=url, ok=False, detail=str(exc))
    status = response.status_code
    ok = 200 <= status < 400
    return ProbeResult(url=url, ok=ok, detail=str(status))


def probe_all(cfg: Config, *, proxy: str | None = None) -> list[ProbeResult]:
    return [probe_url(cfg, url, proxy=proxy) for url in cfg.network.probe_urls]


def proxy_candidates(cfg: Config) -> tuple[str, ...]:
    """Configured proxies, then direct (""). Dedup while preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for proxy in (*cfg.network.proxies, ""):
        key = proxy.strip()
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return tuple(out)


def select_working_proxy(cfg: Config) -> tuple[ProxyAttempt | None, tuple[ProxyAttempt, ...]]:
    """Try each proxy then direct; return (winner or None, all attempts)."""
    attempts: list[ProxyAttempt] = []
    for proxy in proxy_candidates(cfg):
        results = tuple(probe_all(cfg, proxy=proxy))
        attempt = ProxyAttempt(proxy=proxy, results=results)
        attempts.append(attempt)
        if attempt.ok:
            return attempt, tuple(attempts)
    return None, tuple(attempts)

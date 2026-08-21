"""URL matching helpers for web resource, PCF and domain rules."""

import re

from mitmproxy import http

Domain = str | list[str] | None


def domain_matches(domain: Domain, host: str) -> bool:
    if domain is None:
        return True
    host = host.lower()
    if isinstance(domain, str):
        return host == domain.lower()
    return any(host == d.lower() for d in domain)


def web_resource_name(request: http.Request) -> str | None:
    """Return the path following the ``webresources`` segment, or None."""
    components = request.path_components
    for i, component in enumerate(components):
        if component.lower() == "webresources":
            name = "/".join(components[i + 1:])
            # path_components drops a trailing slash; keep it so dev-server root
            # requests (e.g. the Vite HMR base URL) still match a rule prefix.
            if name and request.path.split("?", 1)[0].endswith("/"):
                name += "/"
            return name
    return None


_pcf_patterns: dict[str, re.Pattern[str]] = {}


def pcf_match(path: str, name: str) -> tuple[str, bool] | None:
    """Match a PCF asset URL. Returns (relative asset path, is_css) or None."""
    pattern = _pcf_patterns.get(name)
    if pattern is None:
        pattern = re.compile(
            r"(?P<css>/css)?(?:/(?:cc_)?|cc_)"
            + re.escape(name)
            + r"(?:\.|/)(?P<rest>[^?]*)",
            re.IGNORECASE,
        )
        _pcf_patterns[name] = pattern
    match = pattern.search(path)
    if match is None:
        return None
    return match.group("rest"), bool(match.group("css"))


def clear_pcf_cache() -> None:
    """Drop compiled PCF patterns; called when rules are reloaded."""
    _pcf_patterns.clear()

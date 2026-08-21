r"""
mitmproxy addon that redirects Dataverse / Dynamics 365 web resources and PCF
control assets to local dev builds or a running dev server. See README.md for
setup and config usage.
"""

# Version 2026-08-20

import asyncio
import ipaddress
import mimetypes
import os
import re
import tomllib
from urllib.parse import urlsplit

from mitmproxy import connection, ctx, http, tls
from mitmproxy.net import tls as net_tls
from OpenSSL import SSL

Domain = str | list[str] | None

# TLS verification is skipped only for upstream connections to these loopback
# hosts (local dev servers with self-signed / mkcert certs).
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}

# type -> the set of keys an entry of that type must contain.
_CONFIG_SCHEMA: dict[str, set[str]] = {
    "single": {"name", "file"},
    "folder": {"name", "folder"},
    "devserver": {"name", "url"},
    "pcf": {"name", "folder"},
}
_OPTIONAL_KEYS = {"type", "domain", "disabled"}

# An "include" entry pulls in the rules from another config file. It is expanded
# away at load time, so it never reaches _validate_config / the request handler.
_INCLUDE_KEYS = {"path"}
_INCLUDE_OPTIONAL_KEYS = {"type", "disabled"}

# Keys the loader attaches to each rule internally; not user-provided.
_INTERNAL_KEYS = {"_base_dir"}

# Safety net against pathological include nesting (cycles are caught separately).
_MAX_INCLUDE_DEPTH = 20


def _config_path() -> str:
    """Absolute path of the TOML config file to load."""
    override = os.environ.get("HUMMINGBIRD_PROXY_CONFIG")
    if override:
        return os.path.abspath(override)
    return os.path.abspath(os.path.join(os.getcwd(), "proxy.config.toml"))


def _load_config(path: str) -> list[dict]:
    """Load and parse the TOML config file into a list of rule dicts."""
    try:
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError:
        raise FileNotFoundError(
            f"proxy config file not found: {path}. "
            "Create a proxy.config.toml or set HUMMINGBIRD_PROXY_CONFIG."
        )
    except tomllib.TOMLDecodeError as err:
        raise ValueError(f"invalid TOML in proxy config {path}: {err}")
    rules = data.get("rules", [])
    if not isinstance(rules, list):
        raise ValueError("proxy config 'rules' must be an array of tables")
    return rules


def _load_rules(path: str, _seen: frozenset[str] = frozenset(), _depth: int = 0) -> tuple[list[dict], set[str]]:
    """Load rules from a config file, expanding any "include" entries.

    Each returned rule carries a "_base_dir" key giving the directory its
    relative paths resolve against, so rules pulled in from another config keep
    resolving against that config's own location. Returns
    (rules, config_paths) where config_paths is every config file touched, used
    to watch them all for changes.
    """
    path = os.path.abspath(path)
    if path in _seen:
        raise ValueError(f"include cycle detected at config {path}")
    if _depth > _MAX_INCLUDE_DEPTH:
        raise ValueError(f"include nesting too deep (>{_MAX_INCLUDE_DEPTH}) at {path}")
    _seen = _seen | {path}
    base_dir = os.path.dirname(path)
    rules: list[dict] = []
    config_paths: set[str] = {path}

    for index, item in enumerate(_load_config(path)):
        if isinstance(item, dict) and item.get("type") == "include":
            label = f"{path} include[{index}]"
            missing = _INCLUDE_KEYS - item.keys()
            if missing:
                raise ValueError(f"{label}: missing keys {sorted(missing)}")
            unknown = item.keys() - (_INCLUDE_KEYS | _INCLUDE_OPTIONAL_KEYS)
            if unknown:
                raise ValueError(f"{label}: unknown keys {sorted(unknown)}")
            if item.get("disabled", False):
                continue
            target = item["path"]
            if not os.path.isabs(target):
                target = os.path.normpath(os.path.join(base_dir, target))
            sub_rules, sub_paths = _load_rules(target, _seen, _depth + 1)
            rules.extend(sub_rules)
            config_paths |= sub_paths
        elif isinstance(item, dict):
            rules.append({**item, "_base_dir": base_dir})
        else:
            rules.append(item)

    return rules, config_paths


def _resolve_path(path: str, base_dir: str) -> str:
    """Convert a path to absolute, relative to its config file's directory."""
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(base_dir, path))


def _validate_config(config: list[dict]) -> list[dict]:
    """Validate CONFIG and return the entries that are not disabled."""
    enabled: list[dict] = []
    for index, item in enumerate(config):
        label = f"CONFIG[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{label}: expected a dict, got {type(item).__name__}")
        item_type = item.get("type")
        if item_type not in _CONFIG_SCHEMA:
            raise ValueError(
                f"{label}: unknown or missing 'type' {item_type!r}; "
                f"expected one of {sorted(_CONFIG_SCHEMA)}"
            )
        required = _CONFIG_SCHEMA[item_type]
        missing = required - item.keys()
        if missing:
            raise ValueError(f"{label} (type={item_type!r}): missing keys {sorted(missing)}")
        unknown = item.keys() - (required | _OPTIONAL_KEYS | _INTERNAL_KEYS)
        if unknown:
            raise ValueError(f"{label} (type={item_type!r}): unknown keys {sorted(unknown)}")
        if not item.get("disabled", False):
            enabled.append(item)
    return enabled


def _domain_matches(domain: Domain, host: str) -> bool:
    if domain is None:
        return True
    host = host.lower()
    if isinstance(domain, str):
        return host == domain.lower()
    return any(host == d.lower() for d in domain)


def _web_resource_name(request: http.Request) -> str | None:
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


def _pcf_match(path: str, name: str) -> tuple[str, bool] | None:
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


def _log_redirect(flow: http.HTTPFlow, rule_type: str, rule_name: str, destination: str) -> None:
    ctx.log.info(
        f"Redirected {flow.request.pretty_url} via {rule_type}:{rule_name} -> {destination}"
    )


def _serve_file(flow: http.HTTPFlow, filepath: str, rule_type: str, rule_name: str, base_dir: str) -> None:
    absolute_path = _resolve_path(filepath, base_dir)
    try:
        with open(absolute_path, "rb") as handle:
            content = handle.read()
    except (FileNotFoundError, IsADirectoryError):
        ctx.log.warn(f"Local file not found for {rule_type}:{rule_name} -> {absolute_path}")
        flow.response = http.Response.make(
            404,
            f"dataverseproxy: local file not found: {absolute_path}".encode(),
            {"Content-Type": "text/plain"},
        )
        return
    content_type = mimetypes.guess_type(absolute_path)[0] or "application/octet-stream"
    flow.response = http.Response.make(200, content, {"Content-Type": content_type})
    _log_redirect(flow, rule_type, rule_name, absolute_path)


def _proxy_to_dev_server(flow: http.HTTPFlow, url: str, web_resource: str, rule_name: str) -> None:
    target = urlsplit(url)
    query = flow.request.path.split("?", 1)[1] if "?" in flow.request.path else ""
    new_path = "/webresources/" + web_resource
    if query:
        new_path += "?" + query
    flow.request.scheme = target.scheme
    flow.request.host = target.hostname or "localhost"
    flow.request.port = target.port or (443 if target.scheme == "https" else 80)
    flow.request.path = new_path
    _log_redirect(flow, "devserver", rule_name, f"{url}{new_path}")


# How often (seconds) to poll the config file for changes.
_CONFIG_POLL_INTERVAL = 1.0


def _config_mtime(path: str) -> float | None:
    """Modification time of the config file, or None if it is missing."""
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def _config_mtimes(paths: set[str]) -> dict[str, float | None]:
    """Modification times for every config file, keyed by path."""
    return {path: _config_mtime(path) for path in paths}


class DataverseProxy:
    def __init__(self, config_path: str) -> None:
        self.config_path = config_path
        rules, self._config_paths = _load_rules(config_path)
        self.config = _validate_config(rules)
        self._config_mtimes = _config_mtimes(self._config_paths)
        self._watch_task: asyncio.Task | None = None

    def running(self) -> None:
        # Start watching the config files for changes once the event loop is up.
        if self._watch_task is None:
            self._watch_task = asyncio.ensure_future(self._watch_config())

    def done(self) -> None:
        if self._watch_task is not None:
            self._watch_task.cancel()
            self._watch_task = None

    async def _watch_config(self) -> None:
        while True:
            await asyncio.sleep(_CONFIG_POLL_INTERVAL)
            mtimes = _config_mtimes(self._config_paths)
            if mtimes == self._config_mtimes:
                continue
            self._config_mtimes = mtimes
            self._reload_config()

    def _reload_config(self) -> None:
        try:
            rules, paths = _load_rules(self.config_path)
            config = _validate_config(rules)
        except (OSError, ValueError) as err:
            ctx.log.warn(f"Config reload failed, keeping previous rules: {err}")
            return
        self.config = config
        self._config_paths = paths
        self._config_mtimes = _config_mtimes(paths)
        _pcf_patterns.clear()
        ctx.log.info(
            f"Reloaded proxy config from {self.config_path} "
            f"({len(config)} active rules across {len(paths)} files)"
        )

    def tls_start_server(self, data: tls.TlsData) -> None:
        # Provide a no-verify TLS context for localhost dev servers only. This runs
        # before the built-in TlsConfig addon; once data.ssl_conn is set, TlsConfig
        # skips the connection, so every other (real) upstream keeps full
        # certificate verification.
        server = data.conn
        if data.ssl_conn is not None or not isinstance(server, connection.Server):
            return
        if not server.address or server.address[0] not in LOOPBACK_HOSTS:
            return

        ssl_ctx = net_tls.create_proxy_server_context(
            method=net_tls.Method.TLS_CLIENT_METHOD,
            min_version=net_tls.Version[ctx.options.tls_version_server_min],
            max_version=net_tls.Version[ctx.options.tls_version_server_max],
            cipher_list=None,
            ecdh_curve=None,
            verify=net_tls.Verify.VERIFY_NONE,
            ca_path=None,
            ca_pemfile=None,
            client_cert=None,
            legacy_server_connect=False,
        )
        ssl_conn = SSL.Connection(ssl_ctx)
        sni = server.sni or server.address[0]
        try:
            ipaddress.ip_address(sni)
        except ValueError:
            ssl_conn.set_tlsext_host_name(sni.encode("idna"))
        alpn_offers = server.alpn_offers or data.context.client.alpn_offers
        if alpn_offers:
            ssl_conn.set_alpn_protos(list(alpn_offers))
        ssl_conn.set_connect_state()
        data.ssl_conn = ssl_conn

    def request(self, flow: http.HTTPFlow) -> None:
        host = flow.request.pretty_host
        web_resource = _web_resource_name(flow.request)

        for item in self.config:
            if not _domain_matches(item.get("domain"), host):
                continue

            item_type = item["type"]

            if item_type == "devserver":
                if web_resource is not None and web_resource.startswith(item["name"]):
                    _proxy_to_dev_server(flow, item["url"], web_resource, item["name"])
                    return

            elif item_type == "single":
                if web_resource == item["name"]:
                    _serve_file(flow, item["file"], item_type, item["name"], item["_base_dir"])
                    return

            elif item_type == "folder":
                if web_resource is not None and web_resource.startswith(item["name"]):
                    relative = web_resource[len(item["name"]):]
                    _serve_file(
                        flow,
                        os.path.join(item["folder"], *relative.split("/")),
                        item_type,
                        item["name"],
                        item["_base_dir"],
                    )
                    return

            elif item_type == "pcf":
                hit = _pcf_match(flow.request.path, item["name"])
                if hit is not None:
                    relative, is_css = hit
                    parts = [item["folder"]]
                    if is_css:
                        parts.append("css")
                    parts.extend(segment for segment in relative.split("/") if segment)
                    _serve_file(flow, os.path.join(*parts), item_type, item["name"], item["_base_dir"])
                    return


CONFIG_PATH = _config_path()

addons = [DataverseProxy(CONFIG_PATH)]

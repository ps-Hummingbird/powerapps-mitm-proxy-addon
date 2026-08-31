"""Response builders: serve local files and relay to a dev server."""

from urllib.parse import urlsplit

import asyncio
import mimetypes
import os

from mitmproxy import ctx, http

from hummingbird_proxy.config import resolve_path

# Fail fast when the dev server is down; a localhost connect is otherwise instant.
_DEV_SERVER_PROBE_TIMEOUT = 1.0

# Explicit types for common web assets; the OS mimetypes DB is unreliable here
# (e.g. Windows maps .js to text/plain, which browsers refuse to execute).
_CONTENT_TYPES = {
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".cjs": "text/javascript",
    ".css": "text/css",
    ".html": "text/html",
    ".htm": "text/html",
    ".json": "application/json",
    ".map": "application/json",
    ".svg": "image/svg+xml",
    ".wasm": "application/wasm",
}


def _log_redirect(flow: http.HTTPFlow, rule_type: str, rule_name: str, destination: str) -> None:
    ctx.log.info(
        f"Redirected {flow.request.pretty_url} via {rule_type}:{rule_name} -> {destination}"
    )


def _is_within(root: str, path: str) -> bool:
    """True if PATH is ROOT itself or nested under it (after normalization)."""
    try:
        return os.path.commonpath([root, path]) == root
    except ValueError:
        # Raised when the paths live on different drives (Windows).
        return False


def serve_file(
    flow: http.HTTPFlow,
    filepath: str,
    rule_type: str,
    rule_name: str,
    base_dir: str,
    root: str | None = None,
) -> None:
    absolute_path = resolve_path(filepath, base_dir)
    if root is not None and not _is_within(resolve_path(root, base_dir), absolute_path):
        ctx.log.warn(f"Blocked path traversal for {rule_type}:{rule_name} -> {absolute_path}")
        flow.response = http.Response.make(
            403,
            b"dataverseproxy: path escapes the configured folder",
            {"Content-Type": "text/plain"},
        )
        return
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
    ext = os.path.splitext(absolute_path)[1].lower()
    content_type = (
        _CONTENT_TYPES.get(ext) or mimetypes.guess_type(absolute_path)[0] or "application/octet-stream"
    )
    flow.response = http.Response.make(200, content, {"Content-Type": content_type})
    _log_redirect(flow, rule_type, rule_name, absolute_path)


async def _dev_server_reachable(host: str, port: int) -> bool:
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), _DEV_SERVER_PROBE_TIMEOUT
        )
    except (OSError, asyncio.TimeoutError):
        return False
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    return True


async def proxy_to_dev_server(
    flow: http.HTTPFlow, url: str, web_resource: str, rule_name: str
) -> None:
    target = urlsplit(url)
    host = target.hostname or "localhost"
    port = target.port or (443 if target.scheme == "https" else 80)
    # Probe first: if we let mitmproxy attempt a dead upstream, it caches the
    # connection error on the client's HTTP/2 tunnel and reuses it for every
    # later request, so the page stays broken until the proxy restarts even
    # after the dev server comes up. Returning our own 502 avoids that cache.
    if not await _dev_server_reachable(host, port):
        ctx.log.warn(f"Dev server unreachable for devserver:{rule_name} -> {host}:{port}")
        flow.response = http.Response.make(
            502,
            f"dataverseproxy: dev server not reachable at {host}:{port} "
            f"(devserver:{rule_name}). Start it and refresh.".encode(),
            {"Content-Type": "text/plain"},
        )
        return
    query = flow.request.path.split("?", 1)[1] if "?" in flow.request.path else ""
    new_path = "/webresources/" + web_resource
    if query:
        new_path += "?" + query
    flow.request.scheme = target.scheme
    flow.request.host = host
    flow.request.port = port
    flow.request.path = new_path
    _log_redirect(flow, "devserver", rule_name, f"{url}{new_path}")

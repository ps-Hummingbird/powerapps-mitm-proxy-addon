"""Response builders: serve local files and relay to a dev server."""

from urllib.parse import urlsplit

import mimetypes

from mitmproxy import ctx, http

from hummingbird_proxy.config import resolve_path


def _log_redirect(flow: http.HTTPFlow, rule_type: str, rule_name: str, destination: str) -> None:
    ctx.log.info(
        f"Redirected {flow.request.pretty_url} via {rule_type}:{rule_name} -> {destination}"
    )


def serve_file(flow: http.HTTPFlow, filepath: str, rule_type: str, rule_name: str, base_dir: str) -> None:
    absolute_path = resolve_path(filepath, base_dir)
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


def proxy_to_dev_server(flow: http.HTTPFlow, url: str, web_resource: str, rule_name: str) -> None:
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

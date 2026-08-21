"""The mitmproxy addon: routes matching requests to local files or dev servers."""

import asyncio
import os

from mitmproxy import ctx, http, tls

from hummingbird_proxy import config, matching, serving
from hummingbird_proxy.tls import start_dev_server_tls


class DataverseProxy:
    def __init__(self, config_path: str) -> None:
        self.config_path = config_path
        rules, self._config_paths = config.load_rules(config_path)
        self.config = config.validate_config(rules)
        self._config_mtimes = config.config_mtimes(self._config_paths)
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
            await asyncio.sleep(config.CONFIG_POLL_INTERVAL)
            mtimes = config.config_mtimes(self._config_paths)
            if mtimes == self._config_mtimes:
                continue
            self._config_mtimes = mtimes
            self._reload_config()

    def _reload_config(self) -> None:
        try:
            rules, paths = config.load_rules(self.config_path)
            new_config = config.validate_config(rules)
        except (OSError, ValueError) as err:
            ctx.log.warn(f"Config reload failed, keeping previous rules: {err}")
            return
        self.config = new_config
        self._config_paths = paths
        self._config_mtimes = config.config_mtimes(paths)
        matching.clear_pcf_cache()
        ctx.log.info(
            f"Reloaded proxy config from {self.config_path} "
            f"({len(new_config)} active rules across {len(paths)} files)"
        )

    def tls_start_server(self, data: tls.TlsData) -> None:
        start_dev_server_tls(data)

    def request(self, flow: http.HTTPFlow) -> None:
        host = flow.request.pretty_host
        web_resource = matching.web_resource_name(flow.request)

        for item in self.config:
            if not matching.domain_matches(item.get("domain"), host):
                continue

            item_type = item["type"]

            if item_type == "devserver":
                if web_resource is not None and web_resource.startswith(item["name"]):
                    serving.proxy_to_dev_server(flow, item["url"], web_resource, item["name"])
                    return

            elif item_type == "single":
                if web_resource == item["name"]:
                    serving.serve_file(flow, item["file"], item_type, item["name"], item["_base_dir"])
                    return

            elif item_type == "folder":
                if web_resource is not None and web_resource.startswith(item["name"]):
                    relative = web_resource[len(item["name"]):]
                    serving.serve_file(
                        flow,
                        os.path.join(item["folder"], *relative.split("/")),
                        item_type,
                        item["name"],
                        item["_base_dir"],
                    )
                    return

            elif item_type == "pcf":
                hit = matching.pcf_match(flow.request.path, item["name"])
                if hit is not None:
                    relative, is_css = hit
                    parts = [item["folder"]]
                    if is_css:
                        parts.append("css")
                    parts.extend(segment for segment in relative.split("/") if segment)
                    serving.serve_file(flow, os.path.join(*parts), item_type, item["name"], item["_base_dir"])
                    return

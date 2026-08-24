"""Loading, validation and change-watching of the TOML proxy config."""

import os
import tomllib

# type -> the set of keys an entry of that type must contain.
_CONFIG_SCHEMA: dict[str, set[str]] = {
    "single": {"web-resource-name", "local-path"},
    "folder": {"web-resource-folder", "local-path"},
    "devserver": {"web-resource-folder", "local-url"},
    "pcf": {"control", "local-path"},
}
_OPTIONAL_KEYS = {"type", "domain", "disabled"}

# An "include" entry pulls in the rules from another config file. It is expanded
# away at load time, so it never reaches validate_config / the request handler.
_INCLUDE_KEYS = {"path"}
_INCLUDE_OPTIONAL_KEYS = {"type", "disabled"}

# Keys the loader attaches to each rule internally; not user-provided.
_INTERNAL_KEYS = {"_base_dir"}

# Safety net against pathological include nesting (cycles are caught separately).
_MAX_INCLUDE_DEPTH = 20

# How often (seconds) to poll the config files for changes.
CONFIG_POLL_INTERVAL = 1.0


def config_path() -> str:
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


def load_rules(path: str, _seen: frozenset[str] = frozenset(), _depth: int = 0) -> tuple[list[dict], set[str]]:
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
            sub_rules, sub_paths = load_rules(target, _seen, _depth + 1)
            rules.extend(sub_rules)
            config_paths |= sub_paths
        elif isinstance(item, dict):
            rules.append({**item, "_base_dir": base_dir})
        else:
            rules.append(item)

    return rules, config_paths


def resolve_path(path: str, base_dir: str) -> str:
    """Convert a path to absolute, relative to its config file's directory."""
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(base_dir, path))


def validate_config(config: list[dict]) -> list[dict]:
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
        # Prefix matching relies on a trailing slash to mark the folder boundary,
        # so normalize it rather than silently mismatching a sibling resource.
        if item_type in ("folder", "devserver") and isinstance(item.get("web-resource-folder"), str):
            if not item["web-resource-folder"].endswith("/"):
                item["web-resource-folder"] += "/"
        if not item.get("disabled", False):
            enabled.append(item)
    return enabled


def _config_mtime(path: str) -> float | None:
    """Modification time of the config file, or None if it is missing."""
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def config_mtimes(paths: set[str]) -> dict[str, float | None]:
    """Modification times for every config file, keyed by path."""
    return {path: _config_mtime(path) for path in paths}

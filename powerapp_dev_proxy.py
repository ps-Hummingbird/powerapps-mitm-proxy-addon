r"""
mitmproxy addon that redirects Dataverse / Dynamics 365 web resources and PCF
control assets to local dev builds or a running dev server. See README.md for
setup and config usage.

mitmdump loads this file via ``-s``; its directory is placed on ``sys.path``
during load, so the sibling ``hummingbird_proxy`` package resolves here. All
implementation lives in that package; this module is just the entrypoint.
"""

from hummingbird_proxy import DataverseProxy, config_path

addons = [DataverseProxy(config_path())]

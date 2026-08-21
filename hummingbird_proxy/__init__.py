"""Dev proxy addon package for Dataverse / Dynamics 365 web resources and PCF controls.

The mitmproxy entrypoint lives in ``powerapp_dev_proxy.py`` at the package root;
it imports :class:`DataverseProxy` from here. See README.md for usage.
"""

from hummingbird_proxy.addon import DataverseProxy
from hummingbird_proxy.config import config_path

__all__ = ["DataverseProxy", "config_path"]

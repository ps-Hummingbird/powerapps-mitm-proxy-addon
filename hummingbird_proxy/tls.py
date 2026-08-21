"""TLS handling for upstream connections to local dev servers.

Verification is skipped only for loopback dev servers (self-signed / mkcert
certs); every real upstream keeps full certificate verification because the
built-in TlsConfig addon handles any connection we leave untouched.
"""

import ipaddress

from mitmproxy import connection, ctx, tls
from mitmproxy.net import tls as net_tls
from OpenSSL import SSL

# Upstream hosts for which TLS verification is skipped.
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def start_dev_server_tls(data: tls.TlsData) -> None:
    """Attach a no-verify TLS context when connecting to a loopback dev server.

    Runs before the built-in TlsConfig addon; once ``data.ssl_conn`` is set,
    TlsConfig skips the connection, so other upstreams keep full verification.
    """
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

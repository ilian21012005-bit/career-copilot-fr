"""Public-only HTTP transport and browser proxy; resolve once, connect to that IP."""

from __future__ import annotations

import atexit
import http.client
import ipaddress
import json
import select
import socket
import socketserver
import ssl
import threading
from urllib.parse import parse_qsl, urljoin, urlsplit


class NetworkPolicyError(ValueError):
    pass


def public_address(value: str) -> bool:
    address = ipaddress.ip_address(value)
    if address.version == 6:
        if address.ipv4_mapped:
            address = address.ipv4_mapped
        elif any(address in ipaddress.ip_network(net) for net in (
            "64:ff9b::/96", "64:ff9b:1::/48", "2002::/16", "2001::/32",
        )):
            return False
    return address.is_global and not address.is_multicast


def target(url: str) -> tuple[str, str, int, str]:
    if not isinstance(url, str) or any(ord(c) <= 32 or ord(c) == 127 for c in url):
        raise NetworkPolicyError("URL invalide")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise NetworkPolicyError("URL HTTP publique requise")
    host = parsed.hostname.rstrip(".").encode("idna").decode("ascii")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port not in {80, 443} or "%" in host or host in {"localhost", "localhost.localdomain"} or host.endswith((".local", ".localhost")):
        raise NetworkPolicyError("Destination interdite")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        try:
            address = ipaddress.ip_address(socket.inet_aton(host))
        except OSError:
            address = None
    if address is not None and not public_address(str(address)):
        raise NetworkPolicyError("Adresse interne interdite")
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    return parsed.scheme, host, port, path


def connect_public(host: str, port: int, timeout: float = 15, *, allowed_ports=(80, 443)) -> socket.socket:
    if port not in allowed_ports:
        raise NetworkPolicyError("Port interdit")
    answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not answers or any(not public_address(item[4][0]) for item in answers):
        raise NetworkPolicyError("Résolution DNS interne interdite")
    error = OSError("Aucune connexion publique disponible")
    for family, socktype, protocol, _, address in answers:
        connection = socket.socket(family, socktype, protocol)
        try:
            connection.settimeout(timeout)
            connection.connect(address)  # Numeric sockaddr: never resolve the hostname again.
            return connection
        except OSError as exc:
            error = exc
            connection.close()
    raise error


def fetch(
    url: str,
    *,
    headers: dict[str, str],
    timeout: float = 12,
    max_bytes: int = 4 * 1024 * 1024,
    include_final_url: bool = False,
    include_headers: bool = False,
    method: str = "GET",
    read_body: bool = True,
    body: bytes | None = None,
) -> tuple[int, bytes] | tuple[int, bytes, str] | tuple[int, bytes, str, dict[str, str]]:
    """Fetch with bounded optional body and redirects; every hop is revalidated."""
    method = method.upper()
    if method not in {"GET", "HEAD", "POST"}:
        raise NetworkPolicyError("Méthode HTTP interdite")
    current_body = body
    current_headers = dict(headers)
    sensitive_names = ("authorization", "cookie", "secret", "password", "token", "api-key", "api_key", "apikey")
    sensitive_request = method == "POST" or any(
        any(marker in str(key).lower() for marker in sensitive_names)
        for key in current_headers
    ) or any(
        any(marker in key.lower() for marker in (*sensitive_names, "app_key", "client_id"))
        for key, _ in parse_qsl(urlsplit(url).query, keep_blank_values=True)
    )
    for hop in range(6):
        scheme, host, port, path = target(url)
        connection_type = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
        connection = connection_type(host, port, timeout=timeout)
        try:
            connection.sock = connect_public(host, port, timeout)
            if scheme == "https":
                connection.sock = ssl.create_default_context().wrap_socket(connection.sock, server_hostname=host)
            if current_body is None:
                connection.request(method, path, headers=current_headers)
            else:
                connection.request(method, path, body=current_body, headers=current_headers)
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308} and response.getheader("Location"):
                if hop == 5:
                    raise NetworkPolicyError("Trop de redirections")
                next_url = urljoin(url, response.getheader("Location"))
                next_scheme, next_host, next_port, _ = target(next_url)
                if scheme == "https" and next_scheme != "https":
                    raise NetworkPolicyError("Redirection HTTPS vers HTTP interdite")
                if method == "POST" and response.status in {301, 302, 303}:
                    method = "GET"
                    current_body = None
                if (scheme, host, port) != (next_scheme, next_host, next_port):
                    if current_body is not None or sensitive_request:
                        raise NetworkPolicyError("Redirection externe de requête sensible interdite")
                    # Un nouvel hôte ne reçoit ni jeton, cookie, ni en-tête personnalisé.
                    safe_headers = {"accept", "accept-language", "user-agent"}
                    current_headers = {key: value for key, value in current_headers.items() if key.lower() in safe_headers}
                url = next_url
                continue
            payload = response.read(max_bytes + 1) if read_body and method != "HEAD" else b""
            if len(payload) > max_bytes:
                raise NetworkPolicyError("Réponse trop volumineuse")
            if include_headers:
                return response.status, payload, url, {key.lower(): val for key, val in response.getheaders()}
            if include_final_url:
                return response.status, payload, url
            return response.status, payload
        finally:
            connection.close()
    raise NetworkPolicyError("Trop de redirections")


def get_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 12,
    max_bytes: int = 4 * 1024 * 1024,
) -> tuple[int, dict | list | None]:
    """Fetch a public JSON endpoint cleanly."""
    merged = {"Accept": "application/json", **(headers or {})}
    status, payload = fetch(url, headers=merged, timeout=timeout, max_bytes=max_bytes)
    try:
        return status, json.loads(payload.decode("utf-8", errors="ignore"))
    except (ValueError, TypeError):
        return status, None


def post_json(
    url: str,
    payload: dict | list,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 12,
    max_bytes: int = 4 * 1024 * 1024,
) -> tuple[int, dict | list | None]:
    """Send a bounded JSON POST to a validated public destination."""
    encoded = json.dumps(payload).encode("utf-8")
    merged = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        **(headers or {}),
    }
    status, raw = fetch(
        url,
        headers=merged,
        timeout=timeout,
        max_bytes=max_bytes,
        method="POST",
        body=encoded,
    )
    try:
        return status, json.loads(raw.decode("utf-8", errors="ignore"))
    except (ValueError, TypeError):
        return status, None


def _relay(client: socket.socket, upstream: socket.socket) -> None:
    while True:
        ready, _, _ = select.select([client, upstream], [], [], 30)
        if not ready:
            return
        for source in ready:
            data = source.recv(65536)
            if not data:
                return
            (upstream if source is client else client).sendall(data)


class _ProxyHandler(socketserver.StreamRequestHandler):
    rbufsize = 0  # Do not consume tunnel/body bytes before handing off the raw socket.

    def handle(self):
        if not self.server.slots.acquire(blocking=False):
            self.request.sendall(b"HTTP/1.1 503 Busy\r\nConnection: close\r\n\r\n")
            return
        try:
            self.request.settimeout(15)
            self._forward()
        except (ValueError, OSError):
            try:
                self.request.sendall(b"HTTP/1.1 403 Destination blocked\r\nConnection: close\r\n\r\n")
            except OSError:
                pass
        finally:
            self.server.slots.release()

    def _forward(self):
        line = self.rfile.readline(8193)
        if len(line) > 8192:
            raise NetworkPolicyError("Requête trop longue")
        method, url, version = line.decode("ascii").strip().split(" ")
        if version not in {"HTTP/1.0", "HTTP/1.1"}:
            raise NetworkPolicyError("Version HTTP invalide")
        _, host, port, path = target("https://" + url if method == "CONNECT" else url)
        headers = []
        total = len(line)
        while True:
            header = self.rfile.readline(8193)
            total += len(header)
            if not header or total > 65536 or len(header) > 8192:
                raise NetworkPolicyError("En-têtes invalides")
            if header == b"\r\n":
                break
            key, _ = header.split(b":", 1)
            if key.lower() not in {b"proxy-authorization", b"proxy-connection", b"connection", b"host"}:
                headers.append(header)
        with connect_public(host, port) as upstream:
            if method == "CONNECT":
                self.request.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
            else:
                authority = f"[{host}]" if ":" in host else host
                upstream.sendall(
                    f"{method} {path} {version}\r\nHost: {authority}:{port}\r\nConnection: close\r\n".encode("ascii")
                    + b"".join(headers) + b"\r\n"
                )
            _relay(self.request, upstream)


class PublicProxy(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self):
        self.slots = threading.BoundedSemaphore(32)
        super().__init__(("127.0.0.1", 0), _ProxyHandler)
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    def close(self):
        self.shutdown()
        self.server_close()
        self.thread.join(timeout=2)


_proxy = None
_lock = threading.Lock()


def browser_proxy() -> PublicProxy:
    global _proxy
    with _lock:
        if _proxy is None:
            _proxy = PublicProxy()
            atexit.register(_proxy.close)
        return _proxy

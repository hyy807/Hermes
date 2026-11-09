"""DNS-vetted HEAD transport: numeric sockets, original Host and verified TLS SNI.

Scope/URL/port authorization belongs to the callers. No proxies, redirects,
address fallback, response-body reads, or automatic retries are performed here.
"""
from contextlib import contextmanager
import http.client
import ipaddress
import socket
import ssl

from yf_tools.assessment_plan import PlanError, ScopeViolation


def approved_addresses(policy, host):
    """Validate an exact-host map entry without performing DNS or connecting."""
    mapping = policy.get('dns_addresses')
    if not isinstance(mapping, dict):
        raise PlanError('explicit dns_addresses map required for domains')
    values = mapping.get(host)
    if not isinstance(values, list) or not values:
        raise PlanError('nonempty dns_addresses list required for exact hostname')
    approved = set()
    for value in values:
        if not isinstance(value, str) or '%' in value:
            raise PlanError('dns_addresses must contain unscoped literal IPs')
        try:
            approved.add(ipaddress.ip_address(value))
        except ValueError as exc:
            raise PlanError('dns_addresses must contain literal IPs, not CIDRs') from exc
    return approved


def resolve(policy, host, port):
    """Veto the whole A/AAAA answer set before permitting any socket connection."""
    approved = approved_addresses(policy, host)
    try:
        records = socket.getaddrinfo(host, port, socket.AF_UNSPEC,
                                     socket.SOCK_STREAM, socket.IPPROTO_TCP)
    except OSError as exc:
        raise PlanError('DNS resolution failed') from exc
    if not records:
        raise PlanError('DNS resolution returned no addresses')
    vetted = []
    for family, socktype, proto, _canonname, sockaddr in records:
        if family not in (socket.AF_INET, socket.AF_INET6) or socktype != socket.SOCK_STREAM:
            raise PlanError('unsupported DNS answer')
        try:
            address = ipaddress.ip_address(sockaddr[0])
        except ValueError as exc:
            raise PlanError('invalid DNS answer') from exc
        if '%' in sockaddr[0] or address not in approved:
            raise ScopeViolation('DNS answer outside approved addresses')
        if address.is_unspecified or address.is_multicast:
            raise PlanError('unsupported DNS address')
        # IPv4-mapped IPv6 must not provide an escape from the private-IP gate.
        effective = getattr(address, 'ipv4_mapped', None) or address
        if (effective.is_loopback or effective.is_private or effective.is_link_local) and policy.get('allow_private_dns') is not True:
            raise ScopeViolation('private DNS addresses require allow_private_dns=true')
        if (family == socket.AF_INET) != (address.version == 4):
            raise PlanError('DNS address family mismatch')
        # Reconstruct from the numeric IP and approved port, not resolver metadata.
        numeric = (str(address), port) if family == socket.AF_INET else (str(address), port, 0, 0)
        record = (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, numeric)
        if record not in vetted:
            vetted.append(record)
    return vetted


class PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host, port, destination, *, timeout=10):
        super().__init__(host, port, timeout=timeout)
        self.destination = destination

    def connect(self):
        # socket.create_connection would call getaddrinfo again; use a numeric
        # sockaddr on an explicit-family socket to prevent DNS rebinding.
        family, socktype, proto, sockaddr = self.destination
        sock = socket.socket(family, socktype, proto)
        try:
            sock.settimeout(self.timeout)
            sock.connect(sockaddr)
        except BaseException:
            sock.close()
            raise
        self.sock = sock


class PinnedHTTPSConnection(PinnedHTTPConnection):
    def __init__(self, host, port, destination, *, timeout=10, context=None):
        super().__init__(host, port, destination, timeout=timeout)
        self.context = context if context is not None else ssl.create_default_context()
        if not self.context.check_hostname or self.context.verify_mode != ssl.CERT_REQUIRED:
            raise PlanError('TLS certificate and hostname verification required')

    def connect(self):
        super().connect()
        try:
            self.sock = self.context.wrap_socket(self.sock, server_hostname=self.host)
        except BaseException:
            self.close()
            raise


@contextmanager
def head(policy, host, port, scheme, path, *, ssl_context=None):
    """One HEAD using the first vetted address; all answers must be approved."""
    if scheme not in ('http', 'https'):
        raise PlanError('HTTP(S) required')
    destinations = resolve(policy, host, port)
    if scheme == 'https':
        connection = PinnedHTTPSConnection(host, port, destinations[0], context=ssl_context)
    else:
        connection = PinnedHTTPConnection(host, port, destinations[0])
    try:
        # http.client creates Host from self.host, never the numeric destination.
        connection.request('HEAD', path or '/', headers={'User-Agent': 'Hermes-HTTPBaseline/0.1'})
        with connection.getresponse() as response:
            yield response
    finally:
        connection.close()

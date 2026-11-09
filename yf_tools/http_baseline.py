"""One HEAD to an approved IP or DNS-pinned domain and port; no redirects."""
import argparse
import ipaddress
import json
from pathlib import Path
import sys
import urllib.error
import urllib.request
import http.client
from urllib.parse import urlsplit
from yf_tools.assessment_plan import build_plan, PlanError
from yf_tools.pinned_http import head

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def inspect(policy, target):
    plan = build_plan(policy, target)
    if 'http_baseline' not in [t['type'] for t in plan['tasks']]:
        raise PlanError('http_baseline not approved')
    url = urlsplit(target)
    if url.scheme not in ('http', 'https') or url.query or url.fragment:
        raise PlanError('explicit HTTP(S) URL without query/fragment required')
    try:
        address = ipaddress.ip_address(plan['host'])
    except ValueError:
        address = None
    if address is not None and (address.is_unspecified or address.is_multicast):
        raise PlanError('unsupported IP address')
    port = url.port or (443 if url.scheme == 'https' else 80)
    ports = policy.get('http_ports')
    if not isinstance(ports, list) or not ports or not all(type(p) is int and 1 <= p <= 65535 for p in ports):
        raise PlanError('explicit http_ports list required')
    if port not in ports:
        raise PlanError('port not approved')
    if address is None:
        try:
            with head(policy, plan['host'], port, url.scheme, url.path or '/') as response:
                return observation(response)
        except (OSError, http.client.HTTPException):
            return transport_error()
    # Disable ambient proxy routing; default TLS verification remains enabled.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    req = urllib.request.Request(target, method='HEAD', headers={'User-Agent':'Hermes-HTTPBaseline/0.1'})
    try:
        response = opener.open(req, timeout=10)
    except urllib.error.HTTPError as exc:
        response = exc
    except (urllib.error.URLError, OSError):
        return transport_error()
    with response:
        return observation(response)


def transport_error():
    return {'kind':'http_baseline', 'status':'transport_error', 'method':'HEAD',
            'redirect_followed':False, 'vulnerability_verified':False}


def observation(response):
    # Only presence flags: target headers may contain secrets or injected instructions.
    names = ['strict-transport-security', 'content-security-policy',
             'x-content-type-options', 'x-frame-options', 'referrer-policy']
    return {'kind':'http_baseline', 'status':'observed', 'method':'HEAD',
            'http_status':response.code, 'redirect_followed':False,
            'vulnerability_verified':False,
            'header_presence':{name: response.headers.get(name) is not None for name in names}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policy', required=True)
    parser.add_argument('--target', required=True)
    args = parser.parse_args()
    try:
        result = inspect(json.loads(Path(args.policy).read_text()), args.target)
    except (ValueError, OSError):
        print('http_baseline: invalid policy or target', file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result['status'] == 'observed' else 2

if __name__ == '__main__':
    sys.exit(main())

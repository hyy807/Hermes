# SPA / RPC-gateway API surfacing and response decryption

Notes behind hunt-playbook item 26/27. Two recurring shapes on Chinese SPA
video/VOD/live sites and on enterprise dashboards that "hide" their backend.

## 1. The API surface is in the request body, not the URL path

Angular/Vue/React apps frequently funnel every call into one gateway:

```text
POST https://<cdn-host>/js
Content-Type: application/json
{"url":"/getWhitelist","params":{...},"sign":"..."}
```

`grep -r '/api/'` on the bundles then returns nothing useful, because the
method name is a **string value inside a JSON body**, not a path.

Finding the pattern:

1. Load the page with request interception on and capture the first 2–3 XHRs
   after a normal render. Look at request bodies, not URLs:

   ```python
   def on_request(p):
       if p.request.method == "POST":
           body = p.request.post_data or ""
           if '"url"' in body: print(p.url, "->", body[:300])
   ```

2. Compute the shape: `{"url": "/<verb><Noun>"}` — collect the observed verbs.
3. Grep the bundles for that shape to enumerate the rest:

   ```bash
   grep -ohE '"/get[A-Za-z]+"|"/search[A-Za-z]+"|"/seven[A-Za-z]+"' app.bundle.js | sort -u
   ```

4. Verify one unauthenticated method first — a body-only gateway rarely
   re-checks auth per method, and an unknown method returns a distinguishable
   error (`{"code":404}` vs `{"code":401}`) that confirms the dispatch.

Pitfalls:

- **Pin one host.** The same gateway is served by several redundant CDN
  hostnames. Rotating hosts per request causes intermittent
  `{"blocked":true}` and looks like WAF behaviour when it is really a
  session/host binding.
- **Signing is often client-side and static** — a `sign` field computed from a
  hardcoded salt in the bundle. Reproduce it rather than dropping it: dropping
  the field usually returns a generic failure.
- **`GET` fallbacks exist** for some methods even when the app only uses POST;
  test both before concluding a method needs auth.

## 2. CryptoJS / OpenSSL "Salted__" response decryption

Ciphertext `U2FsdGVkX18...` decodes to `Salted__` — that is CryptoJS's default
OpenSSL-compatible format, **EVP_BytesToKey (MD5, 1 iteration)**:

```text
D1 = MD5(passphrase + salt)
D2 = MD5(D1 + passphrase + salt)
D3 = MD5(D2 + passphrase + salt)
key = D1 || D2            # 32 bytes → AES-256-CBC
iv  = D3                  # 16 bytes
```

The classic mistake: using `D1` as the IV. Symptom is *"the first ~16 bytes are
garbage, the rest is readable"* — that is not corrupted data, it is the wrong
IV. If the whole body is garbage, the passphrase is wrong.

Working decryption (no pycryptodome needed if `cryptography` is present):

```python
import base64, hashlib
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

SALTED = b"Salted__"

def evp_bytes_to_key(passphrase: bytes, salt: bytes, key_len=32, iv_len=16):
    d = b""
    prev = b""
    while len(d) < key_len + iv_len:
        prev = hashlib.md5(prev + passphrase + salt).digest()
        d += prev
    return d[:key_len], d[key_len:key_len + iv_len]

def decrypt_cryptojs(blob: str | bytes, passphrase: str) -> bytes:
    raw = base64.b64decode(blob) if isinstance(blob, str) else blob
    assert raw[:8] == SALTED, f"not OpenSSL-salted: {raw[:8]!r}"
    salt, ct = raw[8:16], raw[16:]
    key, iv = evp_bytes_to_key(passphrase.encode(), salt)
    dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    out = dec.update(ct) + dec.finalize()
    pad = out[-1]
    if 1 <= pad <= 16:
        out = out[:-pad]                      # CryptoJS PKCS#7
    return out
```

Finding the passphrase: it is usually a short literal in the bundle —

```bash
grep -oE 'Utf8\.parse\("[^"]{1,32}"\)|AES\.(encrypt|decrypt)\([^,]{0,40}' app.js | sort -u
grep -oE 'secret\s*[:=]\s*"[^"]{1,32}"|key\s*[:=]\s*"[^"]{1,32}"' app.js | sort -u
```

Once one response decrypts, every endpoint using the same gateway decrypts —
and the plaintext is usually the intelligence you actually wanted (channel
lists, ad config, full media metadata, invite codes, sometimes an internal API
token).

Round-trip test (keeps the implementation honest — run it in the workdir; the
ciphertext it produces starts with `U2FsdGVkX19`, the same prefix you see on
the wire):

```python
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
import os, hashlib, base64

def encrypt_cryptojs(passphrase: str, plain: bytes) -> str:
    salt = os.urandom(8)
    key, iv = evp_bytes_to_key(passphrase.encode(), salt)
    pad = 16 - len(plain) % 16
    enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ct = enc.update(plain + bytes([pad]) * pad) + enc.finalize()
    return base64.b64encode(b"Salted__" + salt + ct).decode()

blob = encrypt_cryptojs("k3y", '{"ok":true}'.encode())
assert decrypt_cryptojs(blob, "k3y") == b'{"ok":true}'
```

## 3. Variants you will meet

| Shape | Tell | Move |
|---|---|---|
| `U2FsdGVkX1...` | `Salted__` prefix | EVP_BytesToKey (this file) |
| Hex ciphertext, no prefix | 32-hex IV prepended | `iv = ct[:16]`, `ct = ct[16:]` |
| AES-GCM with `nonce\|tag\|ct` | 3-part base64 | `modes.GCM`, tag from middle block |
| XOR with a repeating key | entropy looks low, plaintext-ish ASCII | recover key by known-plaintext (`{"` `:` `}`) |
| RSA-wrapped AES key per request | a second field named `key`/`sk` | read the public key from the bundle; the *server* also accepts plaintext if you drop the wrapper in old builds |
| "Encrypted" only in the UI | response is base64 of gzip | `base64 -d \| gunzip` |

## 4. When to stop

If the gateway signs requests with a **server-issued per-session token** and
rejects replay within N seconds, reversing further is usually a bigger job than
finding the same data through an authenticated path. Note the finding as
"client-side gateway, no per-method authz" with one unauth example, and move
on — the report value is the missing authz, not a full signer implementation.

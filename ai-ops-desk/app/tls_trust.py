"""Make Python trust the operating system's certificate store.

Corporate networks (e.g. Splunk's) frequently intercept outbound TLS with a
MITM proxy whose root CA is installed in the OS trust store (macOS Keychain,
Windows cert store, or the system CA bundle on Linux) but is NOT present in the
``certifi`` bundle that Python's ``ssl``/``httpx`` use by default. The symptom
is every external HTTPS call (notably OpenAI) failing with:

    [SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer certificate

``truststore`` re-points Python's ``ssl`` module at the OS trust store, which
already trusts the corporate CA, so those calls succeed.

Importing this module performs the injection as a side effect. It is a safe
no-op when ``truststore`` isn't installed or injection fails (e.g. in cloud
environments like Railway where ``certifi`` already works), so it never breaks
a working setup.
"""

try:
    import truststore

    truststore.inject_into_ssl()
except Exception:
    # No truststore, or injection unsupported on this platform: fall back to
    # the default certifi behavior. Environments without TLS interception are
    # unaffected.
    pass

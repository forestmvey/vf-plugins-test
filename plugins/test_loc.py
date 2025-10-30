import requests

def process_scheduled_call(influxdb3_local, call_time, args=None):
    url = f"http://example.com"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()  # Raise error for HTTP errors
        influxdb3_local.info(response.text)         # Print the JSON credentials
    except requests.RequestException as e:
        influxdb3_local.info(f"Error fetching credentials: {e}")

import boto3

def process_scheduled_call(influxdb3_local, call_time, args=None):
    # Create a session (uses your default profile or environment variables)
    session = boto3.Session()

    # Get the credentials object
    credentials = session.get_credentials()

    # Resolve the credentials (in case they're lazy-loaded)
    creds = credentials.get_frozen_credentials()

    # Print them out
    influxdb3_local.info(f"Caller identity ARN: " + creds.access_key)



import boto3
def process_scheduled_call(influxdb3_local, call_time, args=None):
    session = boto3.Session()
    credentials = session.get_credentials()
    creds = credentials.get_frozen_credentials()
    influxdb3_local.info("Caller identity ARN: " + creds.access_key)

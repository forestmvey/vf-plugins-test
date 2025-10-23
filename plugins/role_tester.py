import botocore.session
import requests

def process_scheduled_call(influxdb3_local, call_time, args=None):
    session = botocore.session.get_session()
    credentials = session.get_credentials().get_frozen_credentials()
    sts = session.create_client('sts')
    identity = sts.get_caller_identity()
    arn = identity['Arn']
    influxdb3_local.info(f"Caller identity ARN: " + arn)
    if ":assumed-role/" in arn:
        role_name = arn.split(":assumed-role/")[1].split("/")[0]
        influxdb3_local.info(f"Role name: " + role_name)
    else:
        ifluxdb3_local.info("Not using an assumed role (may be a user or root identity).")



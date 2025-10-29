import os

def process_scheduled_call(influxdb3_local, call_time, args=None):
    influxdb3_local.info("HTTP_PROXY:", os.environ.get("HTTP_PROXY"))
    influxdb3_local.info("NO_PROXY:", os.environ.get("NO_PROXY"))


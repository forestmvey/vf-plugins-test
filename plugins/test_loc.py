import os
import sys

def process_scheduled_call(influxdb3_local, call_time, args=None):
    cwd = os.getcwd()
    influxdb3_local.info(f"Current working directory: {cwd}")
    in_venv = "Failed"
    if hasattr(sys, 'real_prefix'):
        in_venv = f"Yes (virtualenv) - real_prefix: {sys.real_prefix}"
    elif sys.prefix != getattr(sys, "base_prefix", sys.prefix):
        in_venv = f"Yes (venv) - base_prefix: {sys.base_prefix}"
    elif os.getenv('VIRTUAL_ENV'):
        in_venv = f"Yes (VIRTUAL_ENV set: {os.getenv('VIRTUAL_ENV')})"
    else:
        in_venv = "No (system Python)"
    influxdb3_local.info("Caller identity ARN: " + in_venv)


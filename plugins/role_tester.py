import urllib.request
def process_scheduled_call(influxdb3_local, call_time, args=None):
    influxdb3_local.info("Detected proxies:", urllib.request.getproxies())


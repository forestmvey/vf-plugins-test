import socket

def process_scheduled_call(influxdb3_local, call_time, args=None):
    host = "169.254.170.2"
    port = 80

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(10)
    try:
        s.connect((host, port))
        influxdb3_local.info("Socket connection successful")
    except Exception as e:
        influxdb3_local.info(f"Socket connection failed: {e}")
    finally:
        s.close()


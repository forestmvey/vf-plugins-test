import sys
import platform
import os
import importlib.util
import pkg_resources
import site
import sysconfig

def process_scheduled_call(influxdb3_local, call_time, args=None):
    print_header("PYTHON VERSION INFO", influxdb3_local)
    influxdb3_local.info(f"Executable : {sys.executable}")
    influxdb3_local.info(f"Version    : {sys.version}")
    influxdb3_local.info(f"Version Info: {sys.version_info}")
    influxdb3_local.info(f"Implementation: {platform.python_implementation()}")
    influxdb3_local.info(f"Build Info : {platform.python_build()}")
    influxdb3_local.info(f"Compiler   : {platform.python_compiler()}")

    print_header("PLATFORM INFO", influxdb3_local)
    influxdb3_local.info(f"Platform   : {platform.platform()}")
    influxdb3_local.info(f"Machine    : {platform.machine()}")
    influxdb3_local.info(f"Processor  : {platform.processor()}")
    influxdb3_local.info(f"System     : {platform.system()}")
    influxdb3_local.info(f"Release    : {platform.release()}")
    influxdb3_local.info(f"Architecture: {platform.architecture()}")
    influxdb3_local.info(f"sysconfig PREFIX: {sysconfig.get_config_var('prefix')}")

    print_header("PYTHON PATHS", influxdb3_local)
    for path in sys.path:
        influxdb3_local.info(" -", path)

    print_header("SITE-PACKAGES PATHS", influxdb3_local)
    for path in site.getsitepackages():
        influxdb3_local.info(" -", path)

    print_header("ENVIRONMENT VARIABLES (filtered)", influxdb3_local)
    for k, v in os.environ.items():
        if "PYTHON" in k or "VIRTUAL" in k or "LD_LIBRARY" in k:
            influxdb3_local.info(f"{k} = {v}")

    print_header("TOP INSTALLED PACKAGES", influxdb3_local)
    try:
        dists = sorted(pkg_resources.working_set, key=lambda d: d.project_name.lower())
        for dist in dists[:50]:  # limit to 50 to avoid very long output
            influxdb3_local.info(f"{dist.project_name}=={dist.version}")
    except Exception as e:
        influxdb3_local.info(f"Error listing packages: {e}")

    print_header("OPTIONAL MODULES", influxdb3_local)
    for mod in ("numpy", "pandas", "requests", "flask", "torch"):
        spec = importlib.util.find_spec(mod)
        influxdb3_local.info(f"{mod}: {'FOUND' if spec else 'missing'}")

    influxdb3_local.info("\nDone.")

def print_header(title, influxdb3_local):
    influxdb3_local.info("\n" + "=" * 80)
    influxdb3_local.info(title)
    influxdb3_local.info("=" * 80)


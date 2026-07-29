
"""
{
    "plugin_type": ["scheduled"],
    "scheduled_args_config": [
        {
            "name": "hostname",
            "example": "localhost",
            "description": "Hostname to tag metrics with",
            "required": false
        }
    ]
}
"""

import sys
import platform

def process_scheduled_call(influxdb3_local, time, args=None):
    if args is None:
        args = {}

    hostname = args.get("hostname", "localhost")

    version_info = sys.version_info

    line = LineBuilder("python_version")\
        .tag("host", hostname)\
        .string_field("version", sys.version)\
        .string_field("implementation", platform.python_implementation())\
        .int64_field("major", version_info.major)\
        .int64_field("minor", version_info.minor)\
        .int64_field("micro", version_info.micro)\
        .string_field("releaselevel", version_info.releaselevel)\
        .string_field("compiler", platform.python_compiler())\
        .string_field("platform", platform.platform())

    influxdb3_local.write(line)
    influxdb3_local.info("Wrote python version: " + sys.version)



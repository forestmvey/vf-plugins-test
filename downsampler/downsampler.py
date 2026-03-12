"""
{
    "plugin_type": ["scheduled", "http"],
    "scheduled_args_config": [
        {
            "name": "source_measurement",
            "example": "home",
            "description": "Name of the source measurement to downsample.",
            "required": true
        },
        {
            "name": "target_measurement",
            "example": "home_downsampled",
            "description": "Name of the target measurement to write downsampled data.",
            "required": true
        },
        {
            "name": "interval",
            "example": "7min",
            "description": "Time interval for downsampling (e.g., '10min', '2h'). Units: 's', 'min', 'h', 'd', 'w', 'm', 'q', 'y'.",
            "required": false
        },
        {
            "name": "window",
            "example": "10s",
            "description": "Time window for each downsampling job (e.g., '1h', '1d'). Units: 's', 'min', 'h', 'd', 'w'.",
            "required": true
        },
        {
            "name": "offset",
            "example": "10min",
            "description": "Time offset to apply to the window (e.g., '10min', '1h'). Units: 's', 'min', 'h', 'd', 'w'.",
            "required": false
        },
        {
            "name": "calculations",
            "example": "avg",
            "description": "Aggregation functions (e.g., 'avg' or 'field1:avg.field2:sum'). Valid functions: avg, sum, min, max, median, count, stddev, first_value, last_value, var, approx_median, moving_avg.",
            "required": false
        },
        {
            "name": "moving_avg_window",
            "example": "7",
            "description": "Number of rows to include in moving average window (e.g., '7' for 7-row window). Only used when calculations includes 'moving_avg'.",
            "required": false
        },
        {
            "name": "partition_by_tags",
            "example": "az.region",
            "description": "Dot-separated tag names to use in PARTITION BY clause for moving_avg calculations. Required when using moving_avg. Use 'none' to disable partitioning entirely.",
            "required": true
        },
        {
            "name": "specific_fields",
            "example": "hum.co",
            "description": "Dot-separated field names to downsample (e.g., 'co.temperature').",
            "required": false
        },
        {
            "name": "excluded_fields",
            "example": "field1.field2.tag1",
            "description": "Dot-separated field and tag names to exclude from downsampling results.",
            "required": false
        },
        {
            "name": "tag_values",
            "example": "room:Kitchen@LivingRoom@Bedroom@'Some value string'",
            "description": "Dot-separated tag filters (e.g., 'tag:value1@value2').",
            "required": false
        },
        {
            "name": "max_retries",
            "example": "5",
            "description": "Maximum number of retries for write operations.",
            "required": false
        },
        {
            "name": "target_database",
            "example": "mydb",
            "description": "Target database for writing downsampled data. If not provided, uses the trigger's database.",
            "required": false
        },
        {
            "name": "config_file_path",
            "example": "config.toml",
            "description": "Path to config file to override args. Format: 'config.toml'.",
            "required": false
        }
    ]
}
"""

import json
import os
import random
import re
import time
import tomli as tomllib
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Tuple, Union, Optional

def parse_time_interval(
    influxdb3_local, args: Dict, key: str, task_id: str
) -> Tuple[int, str]:
    """
    Parses the interval string into a tuple of magnitude and unit for downsampling.

    Supports time units: seconds (s), minutes (min), hours (h), days (d), weeks (w),
    months (m), quarters (q), and years (y). Months, quarters, and years are converted
    to days using approximate values: 1 month ≈ 30.42 days, 1 quarter ≈ 91.25 days,
    1 year = 365 days.

    Args:
        influxdb3_local: InfluxDB client instance for querying the database.
        args (dict): Dictionary containing configuration parameters, including the 'interval' key
            with a string in the format '<number><unit>' (e.g., '10min', '2m', '1y').
        key (str): The key used to access the 'key' parameter in the 'args' dictionary.
        task_id (str): The task ID.

    Returns:
        tuple[int, str]: A tuple containing the magnitude (integer) and the unit (e.g., 'minutes' or 'days').
            For months, quarters, and years, the magnitude is the equivalent number of days, and the unit is 'days'.

    Raises:
        Exception: If the interval format is invalid, the unit is not supported, or the magnitude is less than 1.

    Example:
        parse_time_interval(influxdb3_local, {'interval': '10min'}, 'interval', 'task_id')
        (10, 'minutes')
        parse_time_interval(influxdb3_local, {'interval': '2m'}, 'interval', 'task_id')
        (60, 'days')  # 2 months ≈ 60.84 days, rounded to 60
        parse_time_interval(influxdb3_local, {'interval': '1y'}, 'interval', 'task_id')
        (365, 'days')
    """
    unit_mapping: Dict = {
        "s": "seconds",
        "sec": "seconds",
        "min": "minutes",
        "h": "hours",
        "d": "days",
        "w": "weeks",
        "m": "days",  # Months converted to days
        "q": "days",  # Quarters converted to days
        "y": "days",  # Years converted to days
    }

    # Conversion factors to days for month, quarter, and year
    day_conversions: Dict = {
        "m": 30.42,  # Average days in a month (365 ÷ 12)
        "q": 91.25,  # Average days in a quarter (365 ÷ 4)
        "y": 365.0,  # Days in a year (non-leap)
    }

    valid_units = unit_mapping.keys()

    if key == "interval":
        interval: str = args.get(key, "10min")
    else:
        interval = args.get(key, "30d")

    match = re.fullmatch(r"(\d+)([a-zA-Z]+)", interval)
    if match:
        number_part, unit = match.groups()
        magnitude: int = int(number_part)
        if unit in valid_units and magnitude >= 1:
            if unit in day_conversions:
                # Convert months, quarters, or years to days
                days: int = int(magnitude * day_conversions[unit])
                return days, "days"
            return magnitude, unit_mapping[unit]

    raise Exception(f"[{task_id}] Invalid {key} format: {interval}.")


def get_aggregatable_fields(
    influxdb3_local, measurement: str, task_id: str
) -> List[str]:
    """
    Retrieves the list of fields in a measurement that can be aggregated (numeric types).

    Args:
        influxdb3_local: InfluxDB client instance for querying the database.
        measurement (str): Name of the measurement to query.
        task_id (str): The task ID.

    Returns:
        list[str]: List of field names with 'Int64', 'Float64', or 'UInt64' data types.

    Raises:
        Exception: If no aggregatable fields are found for the measurement.
    """
    query: str = """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = $measurement
        AND data_type IN ('Int64', 'Float64', 'UInt64')
    """

    fields: List[Dict] = influxdb3_local.query(query, {"measurement": measurement})

    if not fields:
        raise Exception(
            f"[{task_id}] No aggregatable fields found for measurement '{measurement}'."
        )

    field_names: List[str] = [field["column_name"] for field in fields]

    return field_names


def parse_excluded_fields_for_http(
    influxdb3_local,
    args: dict,
    aggregatable_fields: list,
    tag_names: list,
    task_id: str,
) -> List[str]:
    """
    Parses excluded_fields for HTTP-based requests, handling both fields and tags.
    Supports wildcard '*' to exclude all tags.

    Args:
        influxdb3_local: InfluxDB client instance.
        args (dict): Dictionary containing the 'excluded_fields' key.
        aggregatable_fields (list): List of aggregatable field names.
        tag_names (list): List of tag names.
        task_id (str): The task ID.

    Returns:
        list[str]: List of valid field/tag names to exclude.
    """
    fields: Union[list, str, None] = args.get("excluded_fields", None)
    result_fields: list = []
    
    if fields is None:
        return result_fields
    
    # Handle wildcard '*' - exclude all tags
    if fields == "*" or fields == ["*"]:
        return list(tag_names)
    
    # Handle list of fields/tags
    if isinstance(fields, list):
        for item in fields:
            if item == "*":
                # Wildcard in list - add all tags
                result_fields.extend(tag_names)
            elif item in aggregatable_fields:
                result_fields.append(item)
            elif item in tag_names:
                result_fields.append(item)
            else:
                influxdb3_local.info(
                    f"[{task_id}] Field/tag '{item}' is not available in measurement."
                )
    
    return list(set(result_fields))  # Remove duplicates


def parse_fields_for_http(
    influxdb3_local,
    measurement: str,
    key: str,
    args: dict,
    aggregatable_fields: list,
    task_id: str,
) -> List[str]:
    """
    Parses fields for HTTP-based downsampling.
    Only processes field names (not tags).

    Args:
        influxdb3_local: InfluxDB client instance.
        args (dict): Dictionary containing the 'key' key with a list of field names.
        measurement (str): Name of the measurement.
        key (str): The key used to access the 'key' parameter in the 'args' dictionary.
        aggregatable_fields (list): List of aggregatable field names in the measurement.
        task_id (str): The task ID.

    Returns:
        list[str]: List of valid field names to exclude from downsampling.
    """
    fields: Union[List, None] = args.get(key, None)
    result_fields: List = []
    if fields is not None:
        # Only process aggregatable fields (not tags)
        for field in fields:
            if field not in aggregatable_fields:
                influxdb3_local.info(
                    f"[{task_id}] Field '{field}' is not available for downsampling '{measurement}'."
                )
            else:
                result_fields.append(field)
    return result_fields


def get_tag_names(influxdb3_local, measurement: str, task_id: str) -> List[str]:
    """
    Retrieves the list of tag names for a measurement.

    Args:
        influxdb3_local: InfluxDB client instance.
        measurement (str): Name of the measurement to query.
        task_id (str): The task ID.

    Returns:
        list[str]: List of tag names with 'Dictionary(Int32, Utf8)' data type.
    """
    query: str = """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = $measurement
        AND data_type = 'Dictionary(Int32, Utf8)'
    """
    res: List[Dict] = influxdb3_local.query(query, {"measurement": measurement})

    if not res:
        influxdb3_local.info(
            f"[{task_id}] No tags found for measurement '{measurement}'."
        )
        return []

    tag_names: List[str] = [tag["column_name"] for tag in res]
    return tag_names


def parse_tag_values_for_scheduler(
    influxdb3_local, args: dict, source_measurement: str, task_id: str
) -> Union[Dict[str, List[str]], None]:
    """
    Parses tag values for scheduler-based downsampling requests.

    Args:
        influxdb3_local: InfluxDB client instance.
        args (dict): Dictionary containing the 'tag_values' key with a dot-separated string
            of tag-value pairs (e.g., 'room:Kitchen@Bedroom@"Some other room"').
        source_measurement (str): Name of the source measurement.
        task_id (str): Task identifier.

    Returns:
        Union[dict[str, list[str]], None]: Dictionary mapping tag names to lists of values,
            or None if no tag values are provided.

    Raises:
        Exception: If the tag-value pair format is invalid (e.g., missing ':' or invalid tag name).
    """
    tag_values: Union[str, None, Dict] = args.get("tag_values", None)
    if tag_values is None:
        return None

    # Use config file
    if args["use_config_file"]:
        if isinstance(tag_values, dict):
            return tag_values
        else:
            raise Exception(
                f"[{task_id}] Invalid tag_values format, expected dict, got: {type(tag_values)}."
            )

    result: Dict = {}
    tag_names: List = get_tag_names(influxdb3_local, source_measurement, task_id)
    tag_name_pattern = re.compile(r"^[a-zA-Z0-9_-]+$")

    pairs: List = tag_values.split(".")
    for pair in pairs:
        if not pair:
            continue  # Skip empty pairs
        parts: List = pair.split(":")
        if len(parts) != 2:
            raise Exception(
                f"[{task_id}] Invalid tag-value pair: '{pair}' (must contain exactly one ':')"
            )
        tag_name, value_str = parts
        if not tag_name_pattern.match(tag_name):
            raise Exception(
                f"[{task_id}] Invalid tag name: '{tag_name}' (must consist of letters, digits, '-', and '_')"
            )
        values: List = value_str.split("@")
        strip_values: List = []
        for value in values:
            if value[0] == value[-1] and value[0] in ('"', "'"):
                strip_values.append(value[1:-1])
            else:
                strip_values.append(value)
        if tag_name in tag_names:
            if tag_name in result:
                result[tag_name] += strip_values
            else:
                result[tag_name] = strip_values
        else:
            influxdb3_local.warn(
                f"[{task_id}] Tag '{tag_name}' does not exist in '{source_measurement}'."
            )

    return result


def parse_tag_values_for_http(
    influxdb3_local, data: dict, source_measurement: str, task_id: str
) -> Union[Dict[str, List[str]], None]:
    """
    Parses tag values for HTTP-based downsampling requests.

    Args:
        influxdb3_local: InfluxDB client instance.
        data (dict): Dictionary containing the 'tag_values' key with a dictionary mapping tag names to lists of values.
        source_measurement (str): Name of the source measurement.
        task_id (str): The task ID.

    Returns:
        Union[dict[str, list[str]], None]: Dictionary mapping tag names to lists of values, or None if no tag values provided.
    """
    tag_value_filters: Union[Dict[str, List[str]], None] = data.get("tag_values", None)

    if tag_value_filters is not None:
        tag_names: List = get_tag_names(influxdb3_local, source_measurement, task_id)
        for tag_name in list(tag_value_filters.keys()):
            if tag_name not in tag_names:
                influxdb3_local.warn(
                    f"[{task_id}] Tag '{tag_name}' does not exist in '{source_measurement}'."
                )
                del tag_value_filters[tag_name]
        return tag_value_filters
    return None


def parse_field_aggregations_for_scheduler(
    influxdb3_local, args: dict, aggregatable_fields: list, excluded_fields: list, task_id: str
) -> List[Tuple[str, str]]:
    """
    Parses field aggregations for scheduler-based downsampling.

    Args:
        influxdb3_local: InfluxDB client instance.
        args (dict): Dictionary containing 'source_measurement' and 'calculations' keys.
            'calculations' can be a single aggregation (e.g., 'avg') or a dot-separated string of field:aggregation pairs.
        aggregatable_fields (list): List of aggregatable field names in the measurement.
        excluded_fields (list): List of field and tag names to exclude from aggregations.
        task_id (str): The task ID.

    Returns:
        list[tuple[str, str]]: List of tuples containing field names and their aggregation functions (e.g., [('co', 'avg')]).

    Raises:
        Exception: If no aggregatable fields are found, or if the aggregation format or type is invalid.
    """
    available_calculations: list = ["avg", "sum", "min", "max", "median", "count", "stddev", "first_value", "last_value", "var", "approx_median", "moving_avg"]
    pattern: str = r"^([^:.]+:[^:.]+)(\.[^:.]+:[^:.]+)*$"
    measurement: str = args["source_measurement"]

    specific_fields: List = parse_fields_for_scheduler(
        influxdb3_local,
        measurement,
        "specific_fields",
        args,
        aggregatable_fields,
        task_id,
    )
    calculations_input: str = args.get("calculations", "avg")

    if specific_fields:
        fields_to_use: List = []
        for field in specific_fields:
            if field in aggregatable_fields:
                fields_to_use.append(field)
            else:
                influxdb3_local.info(
                    f"[{task_id}] Field '{field}' is not available for aggregation in measurement '{measurement}'."
                )
    else:
        fields_to_use = aggregatable_fields

    result: List = []
    if not re.match(pattern, calculations_input):
        if calculations_input not in available_calculations:
            raise Exception(
                f"[{task_id}] Aggregation '{calculations_input}' is not available."
            )

        result = [
            (field, calculations_input)
            for field in fields_to_use
            if field not in excluded_fields
        ]
    else:
        calculations: List = calculations_input.split(".")
        used_fields: List = []
        for calc in calculations:
            field_name, calculation = calc.split(":")
            if calculation not in available_calculations:
                raise Exception(
                    f"[{task_id}] Aggregation '{calculations_input}' is not available."
                )
            if field_name in fields_to_use and field_name not in excluded_fields:
                result.append((field_name, calculation))
                used_fields.append(field_name)
            else:
                influxdb3_local.info(
                    f"[{task_id}] Field '{field_name}' is not available or excluded."
                )

        for field in fields_to_use:
            if field not in used_fields:
                result.append((field, "avg"))

    if not result:
        raise Exception(f"[{task_id}] No aggregatable fields found for measurement.")
    return result


def parse_field_aggregations_for_http(
    influxdb3_local, data: dict, aggregatable_fields: list, excluded_fields: list, task_id: str
) -> List[Tuple[str, str]]:
    """
    Parses field aggregations for HTTP-based downsampling.

    Args:
        influxdb3_local: InfluxDB client instance.
        data (dict): Dictionary containing 'source_measurement' and 'calculations' keys.
            'calculations' can be 'avg' or a list of list with 'field' and 'aggregation' (e.g., [['co', 'avg']]).
        aggregatable_fields (list): List of aggregatable field names in the measurement.
        excluded_fields (list): List of field and tag names to exclude from aggregations.
        task_id (str): The task ID.

    Returns:
        list[tuple[str, str]]: List of tuples containing field names and their aggregation functions.

    Raises:
        Exception: If no aggregatable fields are found, or if the aggregation format or type is invalid.
    """
    measurement: str = data["source_measurement"]
    calculations_input: Union[List[List[str, str]], str] = data.get("calculations", "avg")

    specific_fields: List = parse_fields_for_http(
        influxdb3_local,
        measurement,
        "specific_fields",
        data,
        aggregatable_fields,
        task_id,
    )
    available_calculations: list = ["avg", "sum", "min", "max", "median", "count", "stddev", "first_value", "last_value", "var", "approx_median", "moving_avg"]

    if specific_fields:
        fields_to_use: List = []
        for field in specific_fields:
            if field in aggregatable_fields and field not in excluded_fields:
                fields_to_use.append(field)
            else:
                influxdb3_local.info(
                    f"[{task_id}] Field '{field}' is not available for aggregation in measurement '{measurement}' or excluded."
                )
    else:
        fields_to_use = [
            field for field in aggregatable_fields if field not in excluded_fields
        ]

    result: List = []

    if calculations_input == "avg":
        result = [(field, calculations_input) for field in fields_to_use]
    else:
        if not isinstance(calculations_input, list):
            raise Exception(
                f"[{task_id}] Invalid calculations format: {calculations_input}."
            )
        used_fields: List = []
        for field, calc in calculations_input:
            if calc not in available_calculations:
                raise Exception(f"[{task_id}] Aggregation '{calc}' is not available.")
            if field in fields_to_use:
                result.append((field, calc))
                used_fields.append(field)
            else:
                influxdb3_local.info(
                    f"[{task_id}] Field '{field}' is not available or excluded."
                )

        for field in fields_to_use:
            if field not in used_fields:
                result.append((field, "avg"))

    if not result:
        raise Exception(
            f"[{task_id}] No aggregatable fields available for downsampling '{measurement}'."
        )
    return result


def parse_excluded_fields_for_scheduler(
    influxdb3_local,
    args: dict,
    aggregatable_fields: list,
    tag_names: list,
    task_id: str,
) -> List[str]:
    """
    Parses excluded_fields for scheduler-based requests, handling both fields and tags.

    Args:
        influxdb3_local: InfluxDB client instance.
        args (dict): Dictionary containing the 'excluded_fields' key.
        aggregatable_fields (list): List of aggregatable field names.
        tag_names (list): List of tag names.
        task_id (str): The task ID.

    Returns:
        list[str]: List of valid field/tag names to exclude.
    """
    fields: Union[str, None] = args.get("excluded_fields", None)
    pattern: str = r"^[A-Za-z0-9][A-Za-z0-9_-]*(\.[A-Za-z0-9][A-Za-z0-9_-]*)*$"

    if fields is None:
        return []

    if not re.fullmatch(pattern, fields):
        raise Exception(f"[{task_id}] Invalid excluded_fields format: {fields!r}.")

    requested: List = fields.split(".")
    valid: List = []

    for item in requested:
        if item in aggregatable_fields:
            valid.append(item)
        elif item in tag_names:
            valid.append(item)
        else:
            influxdb3_local.info(
                f"[{task_id}] Field/tag '{item}' is not available in measurement."
            )

    return valid


def parse_fields_for_scheduler(
    influxdb3_local,
    measurement: str,
    key: str,
    args: dict,
    aggregatable_fields: list,
    task_id: str,
) -> List[str]:
    """
    Parses fields for downsampling in scheduler-based requests.

    Args:
        influxdb3_local: InfluxDB client instance.
        measurement (str): Name of the measurement.
        args (dict): Dictionary containing the 'key' key with a dot-separated
            string of field names (e.g., 'co.temperature').
        key (str): The key used to access the 'key' parameter in the 'args' dictionary.
        aggregatable_fields (list): List of aggregatable field names in the measurement.
        task_id (str): The task ID.

    Returns:
        list[str]: List of valid field names that exist in the measurement.

    Raises:
        Exception: If the 'key' format is invalid.
    """
    fields: Union[str, None] = args.get(key, None)
    # Field names must start with letter or digit, may contain letters, digits, dashes or underscores,
    # and are separated by dots.
    pattern: str = r"^[A-Za-z0-9][A-Za-z0-9_-]*(\.[A-Za-z0-9][A-Za-z0-9_-]*)*$"

    if fields is None:
        return []

    if not re.fullmatch(pattern, fields):
        raise Exception(f"[{task_id}] Invalid specific_fields format: {fields!r}.")

    requested: List = fields.split(".")
    valid: List = []

    for field in requested:
        if field not in aggregatable_fields:
            influxdb3_local.info(
                f"[{task_id}] Field '{field}' is not available for downsampling '{measurement}'."
            )
        else:
            valid.append(field)

    return valid


def parse_partition_by_tags_for_scheduler(
    influxdb3_local,
    args: dict,
    all_tags: list,
    task_id: str,
) -> List[str]:
    """
    Parses partition_by_tags for scheduler-based requests.
    Required when using moving_avg calculations.

    Args:
        influxdb3_local: InfluxDB client instance.
        args (dict): Dictionary containing the 'partition_by_tags' key.
        all_tags (list): List of all available tag names in the measurement.
        task_id (str): The task ID.

    Returns:
        list[str]: List of valid tag names to use in PARTITION BY clause.
                   Empty list if 'none' is specified.

    Raises:
        Exception: If partition_by_tags is missing when moving_avg is used,
                   or if format is invalid.
    """
    partition_tags: Union[str, None] = args.get("partition_by_tags", None)
    
    if partition_tags is None:
        return None  # Will be validated later if moving_avg is used
    
    # Handle 'none' to disable partitioning
    if partition_tags.lower() == "none":
        return []
    
    # Validate format: dot-separated tag names
    pattern: str = r"^[A-Za-z0-9][A-Za-z0-9_-]*(\.[A-Za-z0-9][A-Za-z0-9_-]*)*$"
    if not re.fullmatch(pattern, partition_tags):
        raise Exception(f"[{task_id}] Invalid partition_by_tags format: {partition_tags!r}.")
    
    requested: List = partition_tags.split(".")
    valid: List = []
    
    for tag in requested:
        if tag in all_tags:
            valid.append(tag)
        else:
            influxdb3_local.warn(
                f"[{task_id}] Tag '{tag}' specified in partition_by_tags does not exist in measurement."
            )
    
    return valid


def parse_partition_by_tags_for_http(
    influxdb3_local,
    args: dict,
    all_tags: list,
    task_id: str,
) -> List[str]:
    """
    Parses partition_by_tags for HTTP-based requests.
    Required when using moving_avg calculations.

    Args:
        influxdb3_local: InfluxDB client instance.
        args (dict): Dictionary containing the 'partition_by_tags' key (list or 'none').
        all_tags (list): List of all available tag names in the measurement.
        task_id (str): The task ID.

    Returns:
        list[str]: List of valid tag names to use in PARTITION BY clause.
                   Empty list if 'none' is specified.

    Raises:
        Exception: If partition_by_tags is missing when moving_avg is used,
                   or if format is invalid.
    """
    partition_tags: Union[List, str, None] = args.get("partition_by_tags", None)
    
    if partition_tags is None:
        return None  # Will be validated later if moving_avg is used
    
    # Handle 'none' string to disable partitioning
    if isinstance(partition_tags, str):
        if partition_tags.lower() == "none":
            return []
        else:
            raise Exception(
                f"[{task_id}] Invalid partition_by_tags format: expected list or 'none', got string '{partition_tags}'."
            )
    
    if not isinstance(partition_tags, list):
        raise Exception(
            f"[{task_id}] Invalid partition_by_tags format: expected list or 'none', got {type(partition_tags).__name__}."
        )
    
    valid: List = []
    for tag in partition_tags:
        if tag in all_tags:
            valid.append(tag)
        else:
            influxdb3_local.warn(
                f"[{task_id}] Tag '{tag}' specified in partition_by_tags does not exist in measurement."
            )
    
    return valid


def parse_max_retries(args: Dict) -> int:
    """
    Parses the maximum number of retries for write operations.

    Args:
        args (dict): Dictionary containing the 'max_retries' key with an integer value.

    Returns:
        int: Maximum number of retries (defaults to 5 if not provided).
    """
    max_retries: Union[int, str] = args.get("max_retries", 5)
    return int(max_retries)


def get_all_tables(influxdb3_local) -> List[str]:
    """
    Retrieves the list of all base tables in the database.

    Args:
        influxdb3_local: InfluxDB client instance.

    Returns:
        list[str]: List of table names with type 'BASE TABLE'.
    """
    result: List = influxdb3_local.query("SHOW TABLES")
    return [
        row["table_name"] for row in result if row.get("table_type") == "BASE TABLE"
    ]


def parse_source_and_target_measurement(
    influxdb3_local, args: Dict, task_id: str
) -> Tuple[str, str]:
    """
    Parses source and target measurement names for downsampling.

    Args:
        influxdb3_local: InfluxDB client instance.
        args (dict): Dictionary containing 'source_measurement' and 'target_measurement' keys.
        task_id (str): The task ID.

    Returns:
        tuple[str, str]: Tuple of source and target measurement names.

    Raises:
        Exception: If 'source_measurement' or 'target_measurement' is missing or if the source measurement does not exist.
    """
    source_measurement: Union[str, None] = args.get("source_measurement", None)
    target_measurement: Union[str, None] = args.get("target_measurement", None)

    if source_measurement is None:
        raise Exception(f"[{task_id}] Missing source_measurement parameter.")
    if target_measurement is None:
        raise Exception(f"[{task_id}] Missing target_measurement parameter.")

    all_tables: List = get_all_tables(influxdb3_local)

    if source_measurement not in all_tables:
        raise Exception(
            f"[{task_id}] Source_measurement {source_measurement} does not exist in database."
        )

    return source_measurement, target_measurement


def parse_offset(args: Dict, task_id: str) -> timedelta:
    """
    Parses the offset string into a timedelta for scheduler-based downsampling.

    Args:
        args (dict): Dictionary containing the 'offset' key with a string in the format '<number><unit>' (e.g., '1h').
        task_id (str): The task ID.

    Returns:
        timedelta: Time delta representing the offset (defaults to 0 if not provided).

    Raises:
        Exception: If the offset format is invalid or the unit is not supported ('s', 'min', 'h', 'd', 'w').
    """
    valid_units: dict = {
        "s": "seconds",
        "min": "minutes",
        "h": "hours",
        "d": "days",
        "w": "weeks",
    }

    offset: Union[str, None] = args.get("offset", None)

    if offset is None:
        return timedelta(0)

    match = re.fullmatch(r"(\d+)([a-zA-Z]+)", offset)
    if match:
        number, unit = match.groups()
        number = int(number)

        if number >= 1 and unit in valid_units:
            return timedelta(**{valid_units[unit]: number})

    raise Exception(f"[{task_id}] Invalid interval format: {offset}.")


def parse_window(args: Dict, task_id: str) -> timedelta:
    """
    Parses the window string into a timedelta for scheduler-based downsampling.

    Args:
        args (dict): Dictionary containing the 'window' key with a string in the format '<number><unit>' (e.g., '1h').
        task_id (str): The task ID.

    Returns:
        timedelta: Time delta representing the window.

    Raises:
        Exception: If the window parameter is missing or the format is invalid.
    """
    valid_units: dict = {
        "s": "seconds",
        "min": "minutes",
        "h": "hours",
        "d": "days",
        "w": "weeks",
    }

    window: Union[str, None] = args.get("window", None)

    if window is None:
        raise Exception(f"[{task_id}] Missing window parameter.")

    match = re.fullmatch(r"(\d+)([a-zA-Z]+)", window)

    if match:
        number, unit = match.groups()
        number = int(number)

        if number >= 1 and unit in valid_units:
            return timedelta(**{valid_units[unit]: number})

    raise Exception(f"[{task_id}] Invalid interval format: {window}.")


def parse_backfill_window(args: Dict, task_id: str) -> Tuple[Union[datetime, None], datetime]:
    """
    Parses the backfill window for HTTP-based downsampling. Requires timezone-aware datetime strings
    in ISO 8601 format (e.g., '2025-05-01T00:00:00+03:00').

    Args:
        args (dict): Dictionary containing 'backfill_start' and 'backfill_end' keys.
        task_id (str): The task ID.

    Returns:
        Tuple[Union[datetime, None], datetime]: Tuple of start and end datetimes in UTC.

    Raises:
        Exception: If the datetime format is invalid, lacks timezone info, or if start ≥ end.
    """

    def parse_iso_datetime(name: str, value: str) -> datetime:
        try:
            dt: datetime = datetime.fromisoformat(value)
        except ValueError:
            raise Exception(
                f"[{task_id}] Invalid ISO 8601 datetime for {name}: '{value}'."
            )
        if dt.tzinfo is None:
            raise Exception(
                f"[{task_id}] {name} must include timezone info (e.g., '+00:00')."
            )
        return dt.astimezone(timezone.utc)

    start_str: Union[str, None] = args.get("backfill_start")
    end_str: Union[str, None] = args.get("backfill_end")

    if end_str:
        backfill_end: datetime = parse_iso_datetime("backfill_end", end_str)
    else:
        backfill_end = datetime.now(timezone.utc)

    if start_str is None:
        return None, backfill_end

    backfill_start: datetime = parse_iso_datetime("backfill_start", start_str)

    if backfill_start >= backfill_end:
        raise Exception(
            f"[{task_id}] backfill_start must be earlier than backfill_end."
        )

    return backfill_start, backfill_end


def generate_fields_string(
    fields_aggregate_list: List[Tuple[str, str]],
    interval: Tuple,
    tags_list: List,
    moving_avg_window: Optional[int] = None,
    include_metadata: bool = True,
):
    """
    Generates the SELECT clause for downsampling.

    Args:
        fields_aggregate_list (list[tuple[str, str]]): List of tuples containing field names and aggregation functions.
        interval (tuple[int, str]): Tuple of interval magnitude and unit (e.g., (10, 'minutes')).
        tags_list (list): List of tag names to include in the query.
        moving_avg_window (Optional[int]): Number of rows for moving average window (default: None).
        include_metadata (bool): If True, includes record_count, time_from, time_to. Default: True.

    Returns:
        str: SQL SELECT clause string including DATE_BIN, aggregations, and optionally time_from, time_to, and tags.
    """
    query: str = f"DATE_BIN(INTERVAL '{interval[0]} {interval[1]}', time, '1970-01-01T00:00:00Z') AS _time"
    
    if include_metadata:
        query += ",\n \
    \tcount(*) AS record_count,\n \
    \tMIN(time) AS time_from,\n \
    \tMAX(time) AS time_to"

    for field in fields_aggregate_list:
        query += ",\n"
        aggregation = field[1]
        field_name = field[0]

        # Add ORDER BY time for first_value and last_value to ensure correct temporal ordering
        if aggregation in ('first_value', 'last_value'):
            query += f'\t{aggregation}("{field_name}" ORDER BY time) as "{field_name}_{aggregation}"'
        elif aggregation == 'moving_avg':
            # Generate moving average using window function
            if moving_avg_window is None:
                moving_avg_window = 7  # Default window size
            
            # Build partition clause with all tags
            partition_clause = ""
            if tags_list:
                partition_parts = [f'"{tag}"' for tag in tags_list]
                partition_clause = f"PARTITION BY {', '.join(partition_parts)} "
            
            query += f'\tAVG("{field_name}") OVER ({partition_clause}ORDER BY time ROWS BETWEEN {moving_avg_window - 1} PRECEDING AND CURRENT ROW) as "{field_name}_moving_avg"'
        else:
            query += f'\t{aggregation}("{field_name}") as "{field_name}_{aggregation}"'

    for tag in tags_list:
        query += f',\n\t"{tag}"'

    return query


def generate_moving_avg_fields_string(
    fields_aggregate_list: List[Tuple[str, str]],
    interval: Tuple,
    partition_tags: List[str],
    moving_avg_window: Optional[int] = None,
):
    """
    Generates the SELECT clause for moving average queries with GROUP BY.

    Uses AVG(AVG(field)) OVER (...) with a time-based RANGE window,
    producing queries that group by time and partition tags.

    Args:
        fields_aggregate_list (list[tuple[str, str]]): List of tuples containing field names and aggregation functions.
        interval (tuple[int, str]): Tuple of interval magnitude and unit (e.g., (10, 'minutes')).
        partition_tags (list[str]): List of tag names to use in PARTITION BY clause and SELECT output for moving averages.
        moving_avg_window (Optional[int]): Window size in seconds for the RANGE interval (default: 7).

    Returns:
        str: SQL SELECT clause string for moving average queries.
    """
    query: str = "time"

    for tag in partition_tags:
        query += f',\n\t"{tag}"'

    for field in fields_aggregate_list:
        query += ",\n"
        aggregation = field[1]
        field_name = field[0]

        if aggregation == 'moving_avg':
            if moving_avg_window is None:
                moving_avg_window = 7

            partition_clause = ""
            if partition_tags:
                partition_parts = [f'"{tag}"' for tag in partition_tags]
                partition_clause = f"PARTITION BY {', '.join(partition_parts)} "

            query += (
                f"\tAVG(AVG(\"{field_name}\")) OVER ("
                f"{partition_clause}"
                f"ORDER BY time "
                f"RANGE BETWEEN INTERVAL '{moving_avg_window} seconds' PRECEDING AND CURRENT ROW"
                f') as "{field_name}_moving_avg"'
            )
        else:
            query += f'\t{aggregation}("{field_name}") as "{field_name}_{aggregation}"'

    return query


def generate_group_by_string(tags_list: List):
    """
    Generates the GROUP BY clause for downsampling queries.

    Args:
        tags_list (list): List of tag names to include in the GROUP BY clause.

    Returns:
        str: SQL GROUP BY clause string including '_time' and tags.
    """
    group_by_clause: str = f"_time"
    for tag in tags_list:
        group_by_clause += f", {tag}"
    return group_by_clause


def generate_tag_filter_clause(tag_values: Union[Dict, None]):
    """
    Generates the WHERE clause for filtering by tag values.

    Args:
        tag_values (Union[dict, None]): Dictionary mapping tag names to lists of values, or None.

    Returns:
        str: SQL WHERE clause string for tag filters, or empty string if tag_values is None.
    """
    if tag_values is None:
        return ""

    sql_clause: str = ""
    for key, values in tag_values.items():
        if len(values) == 1:
            sql_clause += f"AND\n\t\"{key}\" = '{values[0]}'\n"
        else:
            quoted_values = ", ".join(f"'{v}'" for v in values)
            sql_clause += f'AND\n\t"{key}" IN ({quoted_values})\n'
    return sql_clause


def build_downsample_query(
    influxdb3_local,
    fields_list: List[Tuple[str, str]],
    measurement: str,
    tags_list: List[str],
    interval: Tuple,
    tag_values: Union[Dict[str, List[str]], None],
    start_time: datetime,
    end_time: datetime,
    moving_avg_window: Optional[int] = None,
    partition_tags: Optional[List[str]] = None,
    include_metadata: bool = True,
) -> str:
    """
    Builds a downsampling SQL query for any mode (HTTP or scheduler), given explicit start/end.

    Args:
        fields_list: [(field, aggregation), ...]
        measurement: source measurement name
        tags_list: list of tag keys to GROUP BY
        interval: (magnitude, unit) for DATE_BIN
        tag_values: optional tag filters {tag: [val1, val2]}
        start_time: UTC datetime for WHERE time > ...
        end_time:   UTC datetime for WHERE time < ...
        moving_avg_window: Number of rows for moving average window (default: None)
        partition_tags: List of tag names to use in PARTITION BY clause for moving averages (default: None)

    Returns:
        A complete SQL query string.
    """
    influxdb3_local.info("Beginning downsample query build")
    # Check if we have moving average calculations
    has_moving_avg = any(agg == 'moving_avg' for _, agg in fields_list)
    
    # ISO timestamps
    start_iso: str = start_time.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    end_iso: str = end_time.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    # tag filters
    tag_filter_clause: str = generate_tag_filter_clause(tag_values)
    
    if has_moving_avg:
        partition_tags_to_use = partition_tags if partition_tags is not None else []
        fields_clause: str = generate_moving_avg_fields_string(fields_list, interval, partition_tags_to_use, moving_avg_window)
        
        # Build GROUP BY from partition tags + time
        group_by_parts = ["1"]
        for i, _ in enumerate(partition_tags_to_use):
            group_by_parts.append(str(i + 2))
        group_by_clause: str = ", ".join(group_by_parts)
        
        query: str = f"""
            SELECT
                {fields_clause}
            FROM
                '{measurement}'
            WHERE
                time >= '{start_iso}'
            AND 
                time < '{end_iso}'
            {tag_filter_clause}
            GROUP BY {group_by_clause}
            ORDER BY time ASC
        """
    else:
        # Standard aggregation query with GROUP BY
        fields_clause: str = generate_fields_string(fields_list, interval, tags_list, moving_avg_window, include_metadata)
        group_by_clause: str = generate_group_by_string(tags_list)
        
        query: str = f"""
            SELECT
                {fields_clause}
            FROM
                '{measurement}'
            WHERE
                time >= '{start_iso}'
            AND 
                time < '{end_iso}'
            {tag_filter_clause}
            GROUP BY
            {group_by_clause}
        """
    
    influxdb3_local.info(f"Downsample query: {query}")
    return query


def write_downsampled_data(
    influxdb3_local,
    data: List,
    max_retries: int,
    target_measurement: str,
    target_database: Union[str, None],
    task_id: str,
):
    """
    Writes downsampled data to the target measurement with retry logic.

    Args:
        influxdb3_local: InfluxDB client instance.
        data (list): List of LineBuilder objects to write.
        max_retries (int): Maximum number of retry attempts for write operations.
        target_measurement (str): Name of the target measurement.
        target_database (Union[str, None]): Target database name, or None to use the default database.
        task_id (str): The task ID.

    Returns:
        Tuple[bool, Union[str, None], int]: Tuple containing success status, error message (if any), and number of retries.
    """
    retry_count: int = 0

    # Calculate metrics for logging
    record_count: int = len(data)
    db_name: Union[str, None] = target_database if target_database else None
    # Log the operation details
    log_data: dict = {
        "records": record_count,
        "database": db_name if db_name else "default",
        "measurement": target_measurement,
        "max_retries": max_retries,
    }
    influxdb3_local.info(f"[{task_id}] Preparing to write downsampled data", log_data)
    try:
        for tries in range(max_retries):
            try:
                for row in data:
                    if db_name:
                        influxdb3_local.write_to_db(db_name, row)
                    else:
                        influxdb3_local.write(row)
                # Log successful write with metrics
                success_log: dict = {
                    "records_written": record_count,
                    "database": db_name,
                    "measurement": target_measurement,
                    "retries": retry_count,
                }
                influxdb3_local.info(
                    f"[{task_id}] Successful write to {target_measurement}", success_log
                )
                return True, None, retry_count

            except Exception as e:
                retry_count += 1
                # Log retry attempt with error details
                retry_log: dict = {
                    "attempt": tries + 1,
                    "max_retries": max_retries,
                    "records": record_count,
                    "database": db_name,
                    "error": str(e),
                }

                influxdb3_local.warn(
                    f"[{task_id}] Error write attempt {tries + 1}", retry_log
                )
                wait_time: float = (2**tries) + random.random()
                time.sleep(wait_time)

                if tries == max_retries - 1:
                    raise

    except Exception as e:
        # Log failure with complete metrics
        failure_log: dict = {
            "records": record_count,
            "database": db_name,
            "measurement": target_measurement,
            "retries": retry_count,
            "error": str(e),
        }

        influxdb3_local.error(f"[{task_id}] Write failed with exception, {failure_log}")
        return False, str(e), retry_count


def transform_to_influx_line(
    data: List[Dict],
    measurement: str,
    fields_list: List[Tuple[str, str]],
    tags_list: List,
) -> List[LineBuilder]:
    """
    Transforms data into LineBuilder objects for writing to InfluxDB.

    Args:
        data (list[dict]): List of data rows as dictionaries.
        measurement (str): Name of the target measurement.
        fields_list (list[tuple[str, str]]): List of tuples containing field names and aggregation functions.
        tags_list (list): List of tag names.

    Returns:
        list[LineBuilder]: List of LineBuilder objects ready for writing to InfluxDB.
    """
    builders: List = []
    fields_mapping: Dict = {
        f"{field}_{aggregate}": f"{field}_{aggregate}"
        for field, aggregate in fields_list
    }

    fields_mapping["record_count"] = "record_count"
    fields_mapping["time_from"] = "time_from"
    fields_mapping["time_to"] = "time_to"

    for row in data:
        builder = LineBuilder(measurement)
        timestamp: int = row.get("_time") or row["time"]
        builder.time_ns(timestamp)
        for tag in tags_list:
            if tag in row and row[tag] is not None:
                builder.tag(tag, str(row[tag]))

        has_fields: bool = False
        for field_key, field_name in fields_mapping.items():
            if field_key in row and row[field_key] is not None:
                value = row[field_key]
                if isinstance(value, int):
                    builder.int64_field(field_name, value)
                elif isinstance(value, float):
                    builder.float64_field(field_name, value)
                else:
                    builder.string_field(field_name, str(value))
                has_fields = True

        if has_fields:
            builders.append(builder)

    return builders


def process_scheduled_call(
    influxdb3_local, call_time: datetime, args: Union[Dict, None] = None
):
    """
    Processes a scheduled downsampling call.

    Args:
        influxdb3_local: InfluxDB client instance.
        call_time (datetime): Time of the scheduled call.
        args (Union[dict, None]): Configuration parameters for downsampling.

    Raises:
        Exception: If no args are provided.
    """
    task_id: str = str(uuid.uuid4())
    influxdb3_local.info(f"[{task_id}] Downsampling task started at {call_time} with args: {args}")

    if args is None:
        influxdb3_local.error(f"[{task_id}] No args provided for plugin.")
        return

    # Override args with config file if specified
    if args:
        path = args.get("config_file_path", None)
        if path:
            try:
                plugin_dir_var: Union[str, None] = os.getenv("PLUGIN_DIR", None)
                if not plugin_dir_var:
                    influxdb3_local.error(
                        f"[{task_id}] Failed to get PLUGIN_DIR env var"
                    )
                    return
                plugin_dir: Path = Path(plugin_dir_var)
                file_path = plugin_dir / path
                influxdb3_local.info(f"[{task_id}] Reading config file {file_path}")
                with open(file_path, "rb") as f:
                    args = tomllib.load(f)
                    args["use_config_file"] = True
                influxdb3_local.info(f"[{task_id}] New args content: {args}")
            except Exception:
                influxdb3_local.error(f"[{task_id}] Failed to read config file")
                return
        else:
            args["use_config_file"] = False

    influxdb3_local.info(
        f"[{task_id}] Starting downsampling schedule for call_time: {call_time}."
    )

    try:
        start_time: float = time.time()
        source_measurement, target_measurement = parse_source_and_target_measurement(
            influxdb3_local, args, task_id
        )
        target_database: Union[str, None] = args.get("target_database", None)
        tag_value_filters: Union[Dict, None] = parse_tag_values_for_scheduler(
            influxdb3_local, args, source_measurement, task_id
        )
        # Get metadata once and reuse
        all_tags: list = get_tag_names(influxdb3_local, source_measurement, task_id)
        aggregatable_fields: list = get_aggregatable_fields(
            influxdb3_local, source_measurement, task_id
        )

        # Parse excluded_fields to filter out both fields and tags
        excluded_items: list = parse_excluded_fields_for_scheduler(
            influxdb3_local,
            args,
            aggregatable_fields,
            all_tags,
            task_id,
        )

        # Filter tags
        tags: list = [tag for tag in all_tags if tag not in excluded_items]

        if args["use_config_file"]:
            fields: List = parse_field_aggregations_for_http(
                influxdb3_local, args, aggregatable_fields, excluded_items, task_id
            )
        else:
            fields: List = parse_field_aggregations_for_scheduler(
                influxdb3_local, args, aggregatable_fields, excluded_items, task_id
            )

        interval: Tuple = parse_time_interval(
            influxdb3_local, args, "interval", task_id
        )
        max_retries: int = parse_max_retries(args)
        offset: timedelta = parse_offset(args, task_id)
        window: timedelta = parse_window(args, task_id)

        # Parse moving average window if specified
        moving_avg_window: Optional[int] = None
        if args.get("moving_avg_window"):
            try:
                moving_avg_window = int(args["moving_avg_window"])
                if moving_avg_window < 1:
                    raise ValueError("moving_avg_window must be >= 1")
            except (ValueError, TypeError) as e:
                influxdb3_local.warn(
                    f"[{task_id}] Invalid moving_avg_window value: {args.get('moving_avg_window')}. Using default."
                )
                moving_avg_window = None

        # Parse partition_by_tags for moving average calculations
        if args["use_config_file"]:
            partition_tags: Optional[List[str]] = parse_partition_by_tags_for_http(
                influxdb3_local, args, all_tags, task_id
            )
        else:
            partition_tags = parse_partition_by_tags_for_scheduler(
                influxdb3_local, args, all_tags, task_id
            )

        # Check if moving_avg is used and partition_by_tags is required
        has_moving_avg = any(agg == 'moving_avg' for _, agg in fields)
        if has_moving_avg and partition_tags is None:
            raise Exception(
                f"[{task_id}] partition_by_tags is required when using moving_avg calculation. "
                "Specify tag names (e.g., 'az.region') or 'none' to disable partitioning."
            )

        call_time_: datetime = call_time.astimezone(timezone.utc)

        real_now: datetime = call_time_ - offset
        real_then: datetime = real_now - window
        influxdb3_local.info(f"[{task_id}] Querying data from {real_then} to {real_now}")

        query: str = build_downsample_query(
            influxdb3_local,
            fields,
            source_measurement,
            tags,
            interval,
            tag_value_filters,
            real_then,
            real_now,
            moving_avg_window,
            partition_tags,
        )

        data: List = influxdb3_local.query(query)

        # Log source data metrics
        source_record_count: int = len(data)
        source_columns: List = list(data[0].keys()) if source_record_count > 0 else []
        source_data_log: dict = {
            "source_records": source_record_count,
            "source_columns": source_columns,
            "time_range": f"{real_then.isoformat()} to {real_now.isoformat()}",
            "measurement": source_measurement,
        }
        influxdb3_local.info(f"[{task_id}] Source data retrieved: {source_data_log}")

        # Check if we have data to process
        if source_record_count == 0:
            influxdb3_local.info(
                f"[{task_id}] No source data to downsample in the specified time range."
            )
            return

        transformed_data: List = transform_to_influx_line(
            data, target_measurement, fields, tags
        )

        # Log transformed data metrics
        transformed_record_count: int = len(transformed_data)

        # Define transform_data_log variable
        transform_data_log: dict = {
            "source_records": source_record_count,
            "transformed_records": transformed_record_count,
            "target_measurement": target_measurement,
            "time_range": f"{real_then.isoformat()} to {real_now.isoformat()}",
        }

        # Sample the first record to get field and tag names (only if we have data)
        if transformed_record_count > 0:
            sample_record = transformed_data[0]
            try:
                # Try different ways to access field names based on LineBuilder implementation
                if hasattr(sample_record, "fields"):
                    if isinstance(sample_record.fields, dict):
                        field_names: List = list(sample_record.fields.keys())
                    elif hasattr(sample_record.fields, "__iter__") and all(
                        hasattr(f, "key") for f in sample_record.fields
                    ):
                        field_names = [field.key for field in sample_record.fields]
                    else:
                        field_names = ["<field details unavailable>"]
                else:
                    field_names = []

                # Do the same for tags
                if hasattr(sample_record, "tags") and sample_record.tags:
                    if isinstance(sample_record.tags, dict):
                        tag_names: List = list(sample_record.tags.keys())
                    elif hasattr(sample_record.tags, "__iter__") and all(
                        hasattr(t, "key") for t in sample_record.tags
                    ):
                        tag_names = [tag.key for tag in sample_record.tags]
                    else:
                        tag_names = ["<tag details unavailable>"]
                else:
                    tag_names = []

                transform_data_log["field_names"] = field_names
                transform_data_log["tag_names"] = tag_names
            except Exception:
                # Fallback in case we can't determine details
                transform_data_log["field_names"] = ["<field extraction error>"]
                transform_data_log["tag_names"] = ["<tag extraction error>"]

        influxdb3_local.info(
            f"[{task_id}] Data transformation complete", transform_data_log
        )
        # Check if we have data to write
        if transformed_record_count == 0:
            influxdb3_local.warn(f"[{task_id}] No data to write after transformation.")
            return

        success, error, retries = write_downsampled_data(
            influxdb3_local,
            transformed_data,
            max_retries,
            target_measurement,
            target_database,
            task_id,
        )

        end_time: float = time.time()
        execution_time: float = end_time - start_time
        if not success:
            influxdb3_local.error(
                f"[{task_id}] Downsampling job failed with {error}, {retries} retries."
            )
            return

        # Final summary log
        summary_log: dict = {
            "execution_time_seconds": round(execution_time, 2),
            "source_records": source_record_count,
            "written_records": transformed_record_count,
            "source_measurement": source_measurement,
            "target_measurement": target_measurement,
            "retries": retries,
        }
        influxdb3_local.info(f"[{task_id}] Downsampling job finished", summary_log)

    except Exception as e:
        influxdb3_local.error(str(e))


def process_request(
    influxdb3_local, query_parameters, request_headers, request_body, args=None
):
    """
    Processes an HTTP request for downsampling.

    Args:
        influxdb3_local: InfluxDB client instance.
        query_parameters: Query parameters from the HTTP request (unused).
        request_headers: HTTP request headers (unused).
        request_body: JSON-encoded request body containing downsampling parameters.
        args: Optional additional arguments (unused).

    Raises:
        Exception: If no request body is provided.)
    """
    task_id: str = str(uuid.uuid4())
    influxdb3_local.info(f"[{task_id}] Downsampling task started")

    if request_body:
        data: Dict = json.loads(request_body)
        influxdb3_local.info(f"[{task_id}] Request data: {data}.")
    else:
        influxdb3_local.error(f"[{task_id}] No request body provided.")
        return {"message": f"[{task_id}] Error: No request body provided."}

    try:
        start_time: float = time.time()

        source_measurement, target_measurement = parse_source_and_target_measurement(
            influxdb3_local, data, task_id
        )
        target_database: Union[str, None] = data.get("target_database", None)
        tag_value_filters: Union[Dict, None] = parse_tag_values_for_http(
            influxdb3_local, data, source_measurement, task_id
        )
        # Get metadata once and reuse
        all_tags: list = get_tag_names(influxdb3_local, source_measurement, task_id)
        aggregatable_fields: list = get_aggregatable_fields(
            influxdb3_local, source_measurement, task_id
        )

        # Parse excluded_fields to filter out both fields and tags
        excluded_items: list = parse_excluded_fields_for_http(
            influxdb3_local,
            data,
            aggregatable_fields,
            all_tags,
            task_id,
        )

        # Filter tags to exclude excluded tags
        tags: list = [tag for tag in all_tags if tag not in excluded_items]

        fields: List = parse_field_aggregations_for_http(influxdb3_local, data, aggregatable_fields, excluded_items, task_id)
        interval: Tuple = parse_time_interval(
            influxdb3_local, data, "interval", task_id
        )
        max_retries: int = parse_max_retries(data)

        batch_size: Tuple = parse_time_interval(
            influxdb3_local, data, "batch_size", task_id
        )
        backfill_start, backfill_end = parse_backfill_window(data, task_id)

        # Parse moving average window if specified
        moving_avg_window: Optional[int] = None
        if data.get("moving_avg_window"):
            try:
                moving_avg_window = int(data["moving_avg_window"])
                if moving_avg_window < 1:
                    raise ValueError("moving_avg_window must be >= 1")
            except (ValueError, TypeError) as e:
                influxdb3_local.warn(
                    f"[{task_id}] Invalid moving_avg_window value: {data.get('moving_avg_window')}. Using default."
                )
                moving_avg_window = None

        # Parse partition_by_tags for moving average calculations
        partition_tags: Optional[List[str]] = parse_partition_by_tags_for_http(
            influxdb3_local, data, all_tags, task_id
        )

        # Parse include_metadata (default: True for backward compatibility)
        include_metadata: bool = data.get("include_metadata", True)

        # Check if moving_avg is used and partition_by_tags is required
        has_moving_avg = any(agg == 'moving_avg' for _, agg in fields)
        if has_moving_avg and partition_tags is None:
            raise Exception(
                f"[{task_id}] partition_by_tags is required when using moving_avg calculation. "
                "Specify tag names as a list (e.g., ['az', 'region']) or 'none' to disable partitioning."
            )

        if backfill_start is None:
            q: str = f"SELECT MIN(time) as _t FROM {source_measurement}"
            res: List = influxdb3_local.query(q)
            oldest: int = res[0].get("_t")

            backfill_start: datetime = datetime.fromtimestamp(
                oldest / 1e9, tz=timezone.utc
            )
            influxdb3_local.info(
                f"[{task_id}] Full mode: from {backfill_start} to {backfill_end}."
            )
        else:
            influxdb3_local.info(
                f"[{task_id}] Window mode: from {backfill_start} to {backfill_end}."
            )

        cursor: datetime = backfill_start
        total_retries: int = 0
        total_source_records: int = 0
        total_written_records: int = 0
        batch_count: int = 0

        magnitude, unit = batch_size
        unit_mapping: Dict = {
            "seconds": lambda x: timedelta(seconds=x),
            "minutes": lambda x: timedelta(minutes=x),
            "hours": lambda x: timedelta(hours=x),
            "days": lambda x: timedelta(days=x),
        }
        batch_delta: timedelta = unit_mapping[unit.lower()](magnitude)

        influxdb3_local.info(
            f"[{task_id}] Starting downsampling for measurement {source_measurement} with fields: {fields} and tags: {tags} to query")

        while cursor < backfill_end:
            batch_count += 1
            batch_end = min(cursor + batch_delta, backfill_end)

            query: str = build_downsample_query(
                influxdb3_local,
                fields,
                source_measurement,
                tags,
                interval,
                tag_value_filters,
                cursor,
                batch_end,
                moving_avg_window,
                partition_tags,
                include_metadata,
            )

            batch_data: List = influxdb3_local.query(query)
            batch_source_count: int = len(batch_data)
            influxdb3_local.info(f"Batch source count returned from query: {batch_source_count}")
            total_source_records += batch_source_count
            influxdb3_local.info(f"Total source records: {total_source_records}")

            # Log batch source data metrics
            source_columns: List = (
                list(batch_data[0].keys()) if batch_source_count > 0 else []
            )
            batch_source_log: dict = {
                "batch": batch_count,
                "time_range": f"{cursor.isoformat()} to {batch_end.isoformat()}",
                "source_records": batch_source_count,
                "source_columns": source_columns[
                    :10
                ],  # Limit to first 10 columns to avoid huge logs
                "source_measurement": source_measurement,
            }
            influxdb3_local.info(
                f"[{task_id}] Batch source data retrieved", batch_source_log
            )
            if batch_source_count == 0:
                influxdb3_local.info(
                    f"[{task_id}] No data in batch {batch_count}, skipping"
                )
                cursor = batch_end
                continue

            transformed_data: List = transform_to_influx_line(
                batch_data, target_measurement, fields, tags
            )

            batch_transformed_count: int = len(transformed_data)
            transform_log: dict = {
                "batch": batch_count,
                "source_records": batch_source_count,
                "transformed_records": batch_transformed_count,
                "target_measurement": target_measurement,
                "time_range": f"{cursor.isoformat()} to {batch_end.isoformat()}",
            }
            influxdb3_local.info(
                f"[{task_id}] Batch data transformation complete", transform_log
            )
            if batch_transformed_count == 0:
                influxdb3_local.warn(
                    f"[{task_id}] No data to write in batch {batch_count} after transformation."
                )
                cursor = batch_end
                continue

            success, result, retries = write_downsampled_data(
                influxdb3_local,
                transformed_data,
                max_retries,
                target_measurement,
                target_database,
                task_id,
            )

            if success:
                total_written_records += batch_transformed_count
            batch_result_log: dict = {
                "batch": batch_count,
                "success": success,
                "source_records": batch_source_count,
                "written_records": batch_transformed_count if success else 0,
                "retries": retries,
                "error": result if not success else None,
            }

            if not success:
                influxdb3_local.warn(
                    f"[{task_id}] Batch {batch_count} write failed", batch_result_log
                )
            else:
                influxdb3_local.info(
                    f"[{task_id}] Batch {batch_count} completed", batch_result_log
                )

            total_retries += retries
            cursor = batch_end

        duration: float = time.time() - start_time

        # Final summary log
        final_summary: dict = {
            "total_batches": batch_count,
            "execution_time_seconds": round(duration, 2),
            "total_source_records": total_source_records,
            "total_written_records": total_written_records,
            "source_measurement": source_measurement,
            "target_measurement": target_measurement,
            "total_retries": total_retries,
            "time_range": f"{backfill_start.isoformat()} to {backfill_end.isoformat()}",
        }

        influxdb3_local.info(
            f"[{task_id}] Downsampling process completed", final_summary
        )

        return {
            "message": f"[{task_id}] Downsampling completed from '{source_measurement}' to '{target_measurement}'"
        }

    except Exception as e:
        influxdb3_local.error(str(e))
        return {"message": str(e)}


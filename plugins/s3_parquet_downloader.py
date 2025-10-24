import os
from urllib.parse import urlparse
import boto3
from botocore.exceptions import ClientError, NoCredentialsError

def process_scheduled_call(influxdb3_local, call_time, args=None):
    """
    Main function to find and download parquet files from S3.
    
    Args:
        influxdb3_local: Logger object for logging messages
        call_time: Time when the function was called
        args: Dictionary containing arguments, should include 's3uri' key
    """
    session = boto3.Session()
    s3_uri = ""
    if args and "s3uri" in args:
        s3_uri = str(args["s3uri"])
    else:
        influxdb3_local.info("s3uri not supplied in args")
    try:
        # Parse S3 URI
        bucket_name, prefix = parse_s3_uri(s3_uri)
        influxdb3_local.info("Searching for parquet files in bucket: " + bucket_name)
        if prefix:
            influxdb3_local.info("With prefix: " + prefix)
        
        # Initialize S3 client
        try:
            s3_client = session.client('s3')
        except NoCredentialsError:
            influxdb3_local.info("Error: AWS credentials not found. Please configure your AWS credentials.")
            influxdb3_local.info("You can use 'aws configure' or set environment variables AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY")
            return
        
        # Find all parquet files
        influxdb3_local.info("Searching for .parquet files...")
        parquet_files = find_parquet_files(s3_client, bucket_name, prefix, influxdb3_local)
        
        if not parquet_files:
            influxdb3_local.info("There are no parquet files")
            return
        
        # Print all parquet files found
        influxdb3_local.info("Found " + str(len(parquet_files)) + " parquet file(s):")
        for i, file_key in enumerate(parquet_files, 1):
            influxdb3_local.info("  " + str(i) + ". " + file_key)
        
        # Download the first parquet file
        first_file = parquet_files[0]
        local_filename = os.path.basename(first_file)
        
        # Handle case where filename might have path separators
        if not local_filename:
            local_filename = first_file.replace('/', '_')
        
        influxdb3_local.info("\nDownloading first parquet file: " + first_file)
        influxdb3_local.info("Saving as: " + local_filename)
        
        success = download_file(s3_client, bucket_name, first_file, local_filename, influxdb3_local)
        
        if success:
            influxdb3_local.info("Successfully downloaded parquet file: " + local_filename)
            
            # Cleanup - delete the downloaded file
            cleanup_file(local_filename, influxdb3_local)
        else:
            influxdb3_local.info("Failed to download parquet file: " + first_file)
            
    except ValueError as e:
        influxdb3_local.info("Error: " + str(e))
    except Exception as e:
        influxdb3_local.info("Unexpected error: " + str(e))


def parse_s3_uri(s3_uri):
    """
    Parse S3 URI to extract bucket name and prefix.
    
    Args:
        s3_uri (str): S3 URI in format s3://bucket-name/prefix/
        
    Returns:
        tuple: (bucket_name, prefix)
    """
    parsed = urlparse(s3_uri)
    if parsed.scheme != 's3':
        raise ValueError("URI must start with 's3://'")
    
    bucket_name = parsed.netloc
    prefix = parsed.path.lstrip('/')
    
    return bucket_name, prefix

def find_parquet_files(s3_client, bucket_name, prefix="", influxdb3_local=None):
    """
    Find all .parquet files in an S3 bucket, including nested directories.
    
    Args:
        s3_client: boto3 S3 client
        bucket_name (str): Name of the S3 bucket
        prefix (str): Prefix to filter objects (optional)
        
    Returns:
        list: List of S3 object keys that are .parquet files
    """
    parquet_files = []
    
    try:
        # Use paginator to handle large buckets
        paginator = s3_client.get_paginator('list_objects_v2')
        page_iterator = paginator.paginate(Bucket=bucket_name, Prefix=prefix)
        
        for page in page_iterator:
            if 'Contents' in page:
                for obj in page['Contents']:
                    if obj['Key'].lower().endswith('.parquet'):
                        parquet_files.append(obj['Key'])
                        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'NoSuchBucket':
            if influxdb3_local:
                influxdb3_local.info("Error: Bucket " + bucket_name + " does not exist.")
        elif error_code == 'AccessDenied':
            if influxdb3_local:
                influxdb3_local.info("Error: Access denied to bucket " + bucket_name + ". Check your AWS credentials and permissions.")
        else:
            if influxdb3_local:
                influxdb3_local.info("Error listing objects in bucket " + bucket_name + ": " + str(e))
        return []
    except Exception as e:
        if influxdb3_local:
            influxdb3_local.info("Unexpected error while listing objects: " + str(e))
        return []
    
    return parquet_files

def download_file(s3_client, bucket_name, s3_key, local_filename, influxdb3_local=None):
    """
    Download a file from S3 to local filesystem.
    
    Args:
        s3_client: boto3 S3 client
        bucket_name (str): Name of the S3 bucket
        s3_key (str): S3 object key
        local_filename (str): Local filename to save the file
        
    Returns:
        bool: True if download successful, False otherwise
    """
    try:
        s3_client.download_file(bucket_name, s3_key, local_filename)
        return True
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'NoSuchKey':
            if influxdb3_local:
                influxdb3_local.info("Error: File " + s3_key + " does not exist in bucket " + bucket_name + ".")
        elif error_code == 'AccessDenied':
            if influxdb3_local:
                influxdb3_local.info("Error: Access denied to file " + s3_key + ". Check your AWS permissions.")
        else:
            if influxdb3_local:
                influxdb3_local.info("Error downloading file " + s3_key + ": " + str(e))
        return False
    except Exception as e:
        if influxdb3_local:
            influxdb3_local.info("Unexpected error downloading file " + s3_key + ": " + str(e))
        return False

def cleanup_file(filename, influxdb3_local=None):
    """
    Delete a local file.
    
    Args:
        filename (str): Path to the file to delete
        influxdb3_local: Logger object for logging messages
    """
    try:
        if os.path.exists(filename):
            os.remove(filename)
            if influxdb3_local:
                influxdb3_local.info("Cleaned up: Deleted " + filename)
        else:
            if influxdb3_local:
                influxdb3_local.info("File " + filename + " not found for cleanup")
    except Exception as e:
        if influxdb3_local:
            influxdb3_local.info("Error deleting file " + filename + ": " + str(e))



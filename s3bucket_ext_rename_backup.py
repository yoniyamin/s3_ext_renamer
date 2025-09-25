from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import boto3
from botocore.config import Config
import os
import signal
import threading
import time
import logging
from logging.handlers import RotatingFileHandler
from botocore.exceptions import ClientError, NoCredentialsError
import tkinter as tk
from tkinter import messagebox
import sys
import atexit
import socket
import argparse
import webview
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, parse_qs
import re

LOCK_FILE = "app.lock"

def remove_lock_file():
    """Remove the lock file on exit."""
    if os.path.exists(LOCK_FILE):
        os.remove(LOCK_FILE)
        logging.info("Lock file removed.")

def show_popup(title, message):
    """Display a popup message using tkinter."""
    root = tk.Tk()
    root.withdraw()  # Hide the main window
    messagebox.showinfo(title, message)
    root.destroy()

def is_port_in_use(port):
    """Check if a local port is in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def find_free_port(start_port=5000, max_attempts=100):
    """Find a free port starting from start_port."""
    for port in range(start_port, start_port + max_attempts):
        if not is_port_in_use(port):
            return port
    return None

# Configure logging to output to both console and file
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Create formatter
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# Create file handler
file_handler = RotatingFileHandler('app.log', maxBytes=10240, backupCount=10)
file_handler.setFormatter(formatter)

# Create console handler
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)

# Add handlers to the logger, preventing duplicates from Flask's reloader
if not logger.handlers:
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

# Correctly set paths for bundled executable
if getattr(sys, 'frozen', False):
    # we are running in a bundle
    base_path = sys._MEIPASS
else:
    # we are running in a normal Python environment
    base_path = os.path.dirname(os.path.abspath(__file__))

template_folder = os.path.join(base_path, 'templates')
static_folder = os.path.join(base_path, 'static')

app = Flask(__name__, template_folder=template_folder, static_folder=static_folder)
app.secret_key = 'your-secret-key-here'  # Required for flash messages
preview_files = []

def shutdown_server():
    """Shutdown the Flask server gracefully"""
    def shutdown():
        logging.info("Server shutdown initiated.")
        time.sleep(1)  # Give time for the response to be sent
        os.kill(os.getpid(), signal.SIGTERM)
    
    thread = threading.Thread(target=shutdown)
    thread.daemon = True
    thread.start()

@app.route("/shutdown", methods=["POST"])
def shutdown():
    """Shutdown the Flask application"""
    try:
        shutdown_server()
        logging.info("Server is shutting down due to /shutdown request.")
        return jsonify({"success": True, "message": "Server shutting down..."})
    except Exception as e:
        logging.error(f"Error during server shutdown: {e}")
        return jsonify({"success": False, "message": f"Error shutting down: {str(e)}"})

def list_matching_files(s3, bucket, prefix, old_ext, recursive=True):
    """List files in S3 bucket that match the criteria"""
    keys = []
    logging.info(
        f"Listing files in bucket '{bucket}' with prefix '{prefix}' and extension '{old_ext}' (recursive: {recursive})")
    try:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key.endswith(old_ext):
                    # If not recursive, skip files in subfolders
                    if not recursive:
                        # Count slashes after the prefix to determine if it's in a subfolder
                        remaining_path = key[len(prefix):] if key.startswith(prefix) else key
                        if '/' in remaining_path:
                            continue  # Skip files in subfolders
                    keys.append(key)
        logging.info(f"Found {len(keys)} matching files.")
    except ClientError as e:
        logging.error(f"ClientError listing files: {e}")
        raise
    except Exception as e:
        logging.error(f"An unexpected error occurred while listing files: {e}")
        raise
    return keys

@app.route("/browse-folders", methods=["POST"])
def browse_folders():
    """Browse folders/prefixes in S3 bucket"""
    try:
        data = request.get_json()
        access_key = data.get("access_key")
        secret_key = data.get("secret_key")
        session_token = data.get("session_token")
        region = data.get("region", "us-east-1")
        bucket = data.get("bucket")
        current_prefix = data.get("prefix", "")

        logging.info(f"Browsing folders for bucket '{bucket}' with prefix '{current_prefix}'")

        if not access_key or not secret_key or not bucket:
            logging.warning("Missing required credentials for browsing folders.")
            return jsonify({"success": False, "message": "Missing required credentials"})

        # Create S3 session and client
        session_kwargs = {
            "aws_access_key_id": access_key,
            "aws_secret_access_key": secret_key,
            "region_name": region
        }
        if session_token:
            session_kwargs["aws_session_token"] = session_token

        session = boto3.Session(**session_kwargs)
        s3 = session.client("s3")

        # List objects with delimiter to get "folders"
        response = s3.list_objects_v2(
            Bucket=bucket,
            Prefix=current_prefix,
            Delimiter='/'
        )

        folders = []
        files = []

        # Get common prefixes (folders)
        for prefix_info in response.get('CommonPrefixes', []):
            folder_name = prefix_info['Prefix']
            display_name = folder_name[len(current_prefix):].rstrip('/')
            if display_name:  # Don't show empty names
                folders.append({
                    'name': display_name,
                    'full_path': folder_name
                })

        # Get files in current level
        for obj in response.get('Contents', []):
            file_key = obj['Key']
            if file_key != current_prefix and not file_key.endswith('/'):
                file_name = file_key[len(current_prefix):]
                if '/' not in file_name:  # Only direct files, not in subfolders
                    files.append({
                        'name': file_name,
                        'full_path': file_key,
                        'size': obj['Size']
                    })

        logging.info(f"Successfully browsed folders. Found {len(folders)} folders and {len(files)} files.")
        return jsonify({
            "success": True,
            "current_prefix": current_prefix,
            "folders": folders,
            "files": files
        })

    except ClientError as e:
        logging.error(f"AWS ClientError during folder browsing: {e}")
        return jsonify({"success": False, "message": f"AWS Error: {str(e)}"})
    except Exception as e:
        logging.error(f"An unexpected error occurred during folder browsing: {e}")
        return jsonify({"success": False, "message": f"Error: {str(e)}"})

@app.route("/test-connection", methods=["POST"])
def test_connection():
    """Test S3 connection with provided credentials"""
    try:
        data = request.get_json()
        access_key = data.get("access_key")
        secret_key = data.get("secret_key")
        session_token = data.get("session_token")
        region = data.get("region", "us-east-1")
        bucket = data.get("bucket")
        check_region = data.get("check_region", False)

        logging.info(f"Testing connection to bucket '{bucket}' with region checking: {check_region}.")

        if not access_key or not secret_key:
            logging.warning("Missing required credentials for connection test.")
            return jsonify({"success": False, "message": "Missing required credentials"})

        # Create S3 session and client
        session_kwargs = {
            "aws_access_key_id": access_key,
            "aws_secret_access_key": secret_key,
            "region_name": region
        }
        if session_token:
            session_kwargs["aws_session_token"] = session_token

        session = boto3.Session(**session_kwargs)
        s3 = session.client("s3")

        # If bucket is provided, test connection to that specific bucket
        if bucket:
            # Test connection by trying to head the bucket
            s3.head_bucket(Bucket=bucket)
            logging.info(f"Successfully performed head_bucket on '{bucket}'.")

            # Also try to list objects to ensure we have proper permissions
            response = s3.list_objects_v2(Bucket=bucket, MaxKeys=1)
            logging.info(f"Successfully listed objects (MaxKeys=1) on '{bucket}'.")

            response_data = {
                "success": True,
                "message": f"Connection successful! Bucket '{bucket}' is accessible."
            }

            # Check bucket region if requested
            if check_region:
                try:
                    # Get bucket location
                    location_response = s3.get_bucket_location(Bucket=bucket)
                    bucket_region = location_response.get('LocationConstraint')
                    
                    # AWS returns None for us-east-1
                    if bucket_region is None:
                        bucket_region = 'us-east-1'
                    
                    logging.info(f"Bucket '{bucket}' is located in region: {bucket_region}")
                    
                    # Compare with selected region
                    if bucket_region != region:
                        response_data["region_mismatch"] = True
                        response_data["bucket_region"] = bucket_region
                        response_data["selected_region"] = region
                        logging.warning(f"Region mismatch: bucket in {bucket_region}, selected {region}")
                    else:
                        response_data["message"] += f" Region matches ({region})."
                        
                except Exception as e:
                    logging.warning(f"Could not determine bucket region: {str(e)}")
                    # Don't fail the whole test for region check issues

            return jsonify(response_data)
        else:
            # Test general credentials by listing buckets
            response = s3.list_buckets()
            bucket_count = len(response.get('Buckets', []))
            logging.info(f"Successfully listed {bucket_count} buckets.")

            return jsonify({
                "success": True,
                "message": f"Connection successful! Found {bucket_count} accessible buckets."
            })

    except NoCredentialsError:
        logging.error("NoCredentialsError: Invalid AWS credentials provided.")
        return jsonify({"success": False, "message": "Invalid AWS credentials"})
    except ClientError as e:
        error_code = e.response['Error']['Code']
        message = ""
        if error_code == 'NoSuchBucket':
            message = f"Bucket '{bucket}' does not exist"
        elif error_code == 'AccessDenied':
            message = "Access denied. Check your credentials and permissions"
        elif error_code == 'InvalidAccessKeyId':
            message = "Invalid Access Key ID"
        elif error_code == 'SignatureDoesNotMatch':
            message = "Invalid Secret Access Key"
        else:
            message = f"AWS Error: {e.response['Error']['Message']}"
        logging.error(f"ClientError during connection test ({error_code}): {message}")
        return jsonify({"success": False, "message": message})
    except Exception as e:
        logging.error(f"An unexpected error occurred during connection test: {e}")
        return jsonify({"success": False, "message": f"Connection error: {str(e)}"})

@app.route("/wizard")
def wizard():
    """S3 Wizard interface for multiple operations"""
    logging.info("Rendering wizard interface")
    return render_template("wizard.html")

@app.route("/generate-presigned-url", methods=["POST"])
def generate_presigned_url():
    """Generate pre-signed URL for S3 upload"""
    try:
        data = request.get_json()
        access_key = data.get("access_key")
        secret_key = data.get("secret_key")
        session_token = data.get("session_token")
        region = data.get("region", "us-east-1")
        bucket = data.get("bucket")
        object_key = data.get("object_key")
        url_type = data.get("url_type", "upload")  # Default to upload
        generate_html = data.get("generate_html", False)  # Generate HTML form
        upload_html = data.get("upload_html", False)  # Upload HTML form to S3
        expiration = int(data.get("expiration", 3600))  # Default 1 hour
        content_type = data.get("content_type")

        logging.info(f"Generating presigned URL for bucket '{bucket}', key '{object_key}'")

        # For download URLs, object_key is required. For upload URLs, it can be empty (root folder)
        if not access_key or not secret_key:
            logging.warning("Missing required credentials for presigned URL generation")
            return jsonify({"success": False, "message": "Missing required credentials (access_key, secret_key)"})
        
        if url_type == "download" and not object_key:
            logging.warning("Missing object_key for download URL")
            return jsonify({"success": False, "message": "Object key is required for download URLs"})
        
        # For upload URLs, object_key can be empty (uploads to root)
        if object_key is None:
            object_key = ""

        # Create S3 session and client
        session_kwargs = {
            "aws_access_key_id": access_key,
            "aws_secret_access_key": secret_key,
            "region_name": region
        }
        if session_token:
            session_kwargs["aws_session_token"] = session_token

        session = boto3.Session(**session_kwargs)
        s3 = session.client(
            "s3",
            config=Config(
                signature_version='s3v4',
                s3={
                    'addressing_style': 'virtual'
                }
            )
        )

        # Prepare conditions for presigned URL
        conditions = []
        fields = {}
        
        # For HTML forms, allow any content type to avoid 403 errors
        # Only add strict content-type condition for PUT URLs, not POST forms
        if generate_html:
            # For HTML forms, don't add any Content-Type condition to allow maximum flexibility
            pass  # No content-type restrictions for HTML upload forms
        elif content_type and content_type.strip():
            # Only add strict content-type for non-HTML forms with actual content type
            conditions.append({"Content-Type": content_type})
            fields["Content-Type"] = content_type
        
        # For HTML forms, we need to handle the key differently to allow filename substitution
        html_key_prefix = None
        timestamp_key_prefix = None
        if generate_html:
            # Store the original object_key as key prefix for HTML form
            html_key_prefix = object_key or ""  # Handle empty object_key (root folder)
            # Ensure key prefix ends with / for folder uploads
            if html_key_prefix and not html_key_prefix.endswith('/'):
                html_key_prefix = html_key_prefix + '/'
            # Generate timestamp-based subfolder to avoid filename conflicts
            timestamp_folder = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
            timestamp_key_prefix = html_key_prefix + timestamp_folder + "/"
            # Add starts-with condition for key to allow any filename after the timestamp prefix
            conditions.append(["starts-with", "$key", timestamp_key_prefix])
            # Set a template key that will be replaced in the HTML form
            object_key = timestamp_key_prefix + "${filename}"

        # Generate presigned URLs based on type
        try:
            # If bucket is not provided, try to extract it from object_key or use default bucket
            if not bucket:
                # Try to extract bucket from object key if it contains s3:// scheme
                if object_key.startswith('s3://'):
                    parts = object_key[5:].split('/', 1)
                    if len(parts) >= 1:
                        bucket = parts[0]
                        object_key = parts[1] if len(parts) > 1 else ''
                else:
                    # If no bucket provided and can't extract, return error
                    return jsonify({"success": False, "message": "Bucket name is required or must be included in object key (s3://bucket-name/path)"})

            if url_type == "download":
                # Generate download URL using GET
                download_url = s3.generate_presigned_url(
                    'get_object',
                    Params={
                        'Bucket': bucket,
                        'Key': object_key
                    },
                    ExpiresIn=expiration,
                    HttpMethod='GET'
                )
                
                # Generate curl command for download
                curl_download = f'curl -L -o "downloaded_file" "{download_url}"'
                
                logging.info(f"Successfully generated download URL for '{object_key}'")
                
                return jsonify({
                    "success": True,
                    "url_type": "download",
                    "download_url": download_url,
                    "curl_download": curl_download,
                    "issued_at": datetime.now(timezone.utc).isoformat(),
                    "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=expiration)).isoformat(),
                    "expiration_seconds": expiration
                })
            
            else:  # upload
                response = s3.generate_presigned_post(
                    Bucket=bucket,
                    Key=object_key,
                    Fields=fields,
                    Conditions=conditions,
                    ExpiresIn=expiration
                )
                
                # Also generate presigned PUT URL for simpler uploads
                put_params = {
                    'Bucket': bucket,
                    'Key': object_key
                }
                if content_type:
                    put_params['ContentType'] = content_type
                    
                put_url = s3.generate_presigned_url(
                    'put_object',
                    Params=put_params,
                    ExpiresIn=expiration,
                    HttpMethod='PUT'
                )

                # Calculate timestamps
                issued_at = datetime.now(timezone.utc)
                expires_at = issued_at + timedelta(seconds=expiration)

                # Generate curl commands
                curl_post = f'curl -X POST'
                for field, value in response['fields'].items():
                    curl_post += f' -F "{field}={value}"'
                curl_post += f' -F "file=@/path/to/your/file" "{response["url"]}"'

                # Generate curl command for PUT upload
                curl_put = f'curl -X PUT'
                if content_type:
                    curl_put += f' -H "Content-Type: {content_type}"'
                curl_put += f' -T "/path/to/your/file" "{put_url}"'

                # Generate HTML form if requested
                html_content = None
                uploaded_html_url = None
                if generate_html:
                    try:
                        logging.info(f"Generating HTML form with key_prefix: {html_key_prefix or object_key}")
                        html_content = generate_upload_html(
                            presigned_post=response,
                            key_prefix=timestamp_key_prefix,
                            expiration_minutes=expiration // 60,
                            max_size_mb=100,  # Default 100MB limit
                            add_timestamp=False  # Timestamp already added in URL generation
                        )
                        logging.info("HTML form generated successfully")
                    except Exception as e:
                        logging.error(f"Error generating HTML form: {e}")
                        raise
                    
                    # Upload HTML form to S3 if requested
                    if upload_html and html_content:
                        try:
                            # Determine HTML file path in S3 using base prefix (not timestamp)
                            html_filename = f"upload-form-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.html"
                            # Use the base html_key_prefix (without timestamp) for the HTML file location
                            base_prefix = html_key_prefix or ""  # Handle empty prefix (root folder)
                            if base_prefix and base_prefix.endswith('/'):
                                html_key = base_prefix + html_filename
                            elif base_prefix:
                                # If prefix is a file path, put HTML in same directory
                                html_key = '/'.join(base_prefix.split('/')[:-1]) + '/' + html_filename if '/' in base_prefix else html_filename
                            else:
                                html_key = html_filename
                            
                            # Upload HTML file to S3 (without ACL to avoid permission issues)
                            s3.put_object(
                                Bucket=bucket,
                                Key=html_key,
                                Body=html_content.encode('utf-8'),
                                ContentType='text/html',
                                CacheControl='no-cache'
                            )
                            
                            # Generate presigned download URL for the uploaded HTML file
                            # Use same expiration as the upload URL
                            uploaded_html_url = s3.generate_presigned_url(
                                'get_object',
                                Params={
                                    'Bucket': bucket,
                                    'Key': html_key
                                },
                                ExpiresIn=expiration,
                                HttpMethod='GET'
                            )
                            logging.info(f"HTML form uploaded to S3: {html_key} with presigned download URL")
                            
                        except Exception as e:
                            logging.error(f"Failed to upload HTML form to S3: {str(e)}")
                            # Continue without failing the whole operation

                # Use html_key_prefix for logging to avoid ${filename} template evaluation
                key_for_logging = html_key_prefix or object_key
                logging.info(f"Successfully generated upload URLs for '{key_for_logging}'" + 
                           (" with HTML form" if generate_html else "") +
                           (" (uploaded to S3)" if uploaded_html_url else ""))

                response_data = {
                    "success": True,
                    "url_type": "upload",
                    "post_url": response["url"],
                    "post_fields": response["fields"],
                    "put_url": put_url,
                    "curl_post": curl_post,
                    "curl_put": curl_put,
                    "issued_at": issued_at.isoformat(),
                    "expires_at": expires_at.isoformat(),
                    "expiration_seconds": expiration
                }
                
                if html_content:
                    response_data["html_form"] = html_content
                    
                if uploaded_html_url:
                    response_data["uploaded_html_url"] = uploaded_html_url
                    
                return jsonify(response_data)

        except ClientError as e:
            logging.error(f"ClientError generating presigned URL: {e}")
            return jsonify({"success": False, "message": f"AWS Error: {str(e)}"})

    except Exception as e:
        logging.error(f"An unexpected error occurred generating presigned URL: {e}")
        return jsonify({"success": False, "message": f"Error: {str(e)}"})

def generate_upload_html(presigned_post, key_prefix, expiration_minutes, max_size_mb=100, add_timestamp=True):
    """Generate a standalone HTML upload form using template
    
    Args:
        presigned_post: The presigned POST data from S3
        key_prefix: The S3 key prefix (may already include timestamp)
        expiration_minutes: How long the form is valid
        max_size_mb: Maximum file size in MB
        add_timestamp: Whether to add timestamp subfolder (False if already added)
    """
    
    # Ensure key_prefix ends with / for folder uploads, or use as-is for file uploads
    if key_prefix and not key_prefix.endswith('/'):
        key_prefix = key_prefix + '/'
    
    # Generate hidden fields for the presigned POST
    hidden_fields = ""
    for field_name, field_value in presigned_post['fields'].items():
        if field_name != 'key':  # We'll handle the key field separately
            # Escape any braces in the field value to prevent format string conflicts
            escaped_value = str(field_value).replace('{', '{{').replace('}', '}}')
            hidden_fields += f'    <input type="hidden" name="{field_name}" value="{escaped_value}"/>\n'
    
    # HTML content now loaded from template file
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Upload Form</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * {{ box-sizing: border-box; }}
        body {{ 
            font-family: system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif; 
            margin: 0; padding: 2rem; 
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
        }}
        .container {{
            max-width: 600px;
            margin: 0 auto;
            background: white;
            border-radius: 15px;
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.1);
            overflow: hidden;
        }}
        .header {{
            background: linear-gradient(135deg, #2c3e50, #34495e);
            color: white;
            padding: 30px;
            text-align: center;
        }}
        .header h1 {{ margin: 0; font-weight: 300; }}
        .header p {{ margin: 10px 0 0 0; opacity: 0.9; }}
        .content {{ padding: 40px; }}
        .form-group {{ margin-bottom: 25px; }}
        label {{ 
            display: block; 
            margin-bottom: 8px; 
            font-weight: 600; 
            color: #2c3e50;
            font-size: 14px;
        }}
        input[type="file"] {{
            width: 100%;
            padding: 15px;
            border: 2px dashed #667eea;
            border-radius: 8px;
            background: #f8f9fa;
            cursor: pointer;
            transition: all 0.3s ease;
        }}
        input[type="file"]:hover {{
            border-color: #2c3e50;
            background: white;
        }}
        .btn {{
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
            border: none;
            padding: 15px 30px;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            width: 100%;
            margin-top: 20px;
        }}
        .btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 10px 25px rgba(102, 126, 234, 0.3);
        }}
        .btn:disabled {{
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }}
        .info-box {{
            background: #d1ecf1;
            color: #0c5460;
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 20px;
            border-left: 4px solid #17a2b8;
            font-size: 14px;
        }}
        .progress-container {{
            margin-top: 20px;
            display: none;
        }}
        progress {{
            width: 100%;
            height: 12px;
            border-radius: 6px;
        }}
        .result {{
            margin-top: 20px;
            padding: 15px;
            border-radius: 8px;
            display: none;
        }}
        .result.success {{
            background: #d4edda;
            color: #155724;
            border-left: 4px solid #28a745;
        }}
        .result.error {{
            background: #f8d7da;
            color: #721c24;
            border-left: 4px solid #dc3545;
        }}
        .details {{
            margin-top: 20px;
            font-size: 14px;
        }}
        .details summary {{
            cursor: pointer;
            font-weight: 600;
            padding: 10px 0;
        }}
        .details-content {{
            padding: 10px 0;
            color: #6c757d;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔗 Upload Form</h1>
            <p>Secure file upload - <span id="timeRemaining">Calculating remaining time...</span></p>
        </div>
        
        <div class="content">
            <div class="info-box">
                <strong>📁 Upload Location:</strong> {upload_location}<br>
                <strong>📊 Max File Size:</strong> {max_size_mb} MB<br>
                <strong>🔒 Security:</strong> Files upload directly to S3 with temporary access
            </div>
            
            <form id="uploadForm" action="{post_url}" method="post" enctype="multipart/form-data">
                {hidden_fields}
                <input type="hidden" name="key" value="{key_with_placeholder}">
                
                <div class="form-group">
                    <label for="fileInput">Choose File to Upload</label>
                    <input id="fileInput" name="file" type="file" required />
                </div>
                
                <button type="submit" class="btn" id="uploadBtn">
                    📤 Upload File
                </button>
                
                <div class="progress-container" id="progressContainer">
                    <progress id="progressBar" value="0" max="100"></progress>
                    <div style="text-align: center; margin-top: 10px;">
                        <span id="progressText">Uploading...</span>
                    </div>
                </div>
                
                <div class="result" id="resultDiv"></div>
            </form>
            
            <div class="details">
                <details>
                    <summary>ℹ️ Technical Details</summary>
                    <div class="details-content">
                        <p><strong>Upload Method:</strong> Direct POST to S3</p>
                        <p><strong>Success Response:</strong> 201 Created with XML</p>
                        <p><strong>Key Pattern:</strong> {key_pattern}</p>
                        <p><strong>Generated:</strong> {generated_time}</p>
                    </div>
                </details>
            </div>
        </div>
    </div>

    <script>
        document.getElementById('uploadForm').addEventListener('submit', function(e) {{
            e.preventDefault();
            
            const fileInput = document.getElementById('fileInput');
            const uploadBtn = document.getElementById('uploadBtn');
            const progressContainer = document.getElementById('progressContainer');
            const progressBar = document.getElementById('progressBar');
            const progressText = document.getElementById('progressText');
            const resultDiv = document.getElementById('resultDiv');
            
            if (!fileInput.files[0]) {{
                alert('Please select a file to upload');
                return;
            }}
            
            const file = fileInput.files[0];
            const maxSize = {max_size_mb} * 1024 * 1024; // Convert MB to bytes
            
            if (file.size > maxSize) {{
                alert(`File size (${{(file.size / 1024 / 1024).toFixed(2)}} MB) exceeds the maximum allowed size ({max_size_mb} MB)`);
                return;
            }}
            
            // Prepare form data
            const formData = new FormData(this);
            
            // Validate and update key with actual filename
            const keyInput = this.querySelector('input[name="key"]');
            
            // Validate S3 object key
            const validationResult = validateS3ObjectKey(file.name);
            if (!validationResult.valid) {{
                alert(`Invalid filename: ${{validationResult.error}}\n\n${{validationResult.hint}}`);
                return;
            }}
            
            keyInput.value = keyInput.value.replace('${filename}', validationResult.sanitizedName);
            
            // Store sanitized filename for success message
            window.sanitizedFilename = validationResult.sanitizedName;
            
            // Show progress
            uploadBtn.disabled = true;
            uploadBtn.textContent = '⏳ Uploading...';
            progressContainer.style.display = 'block';
            resultDiv.style.display = 'none';
            
            // Create XMLHttpRequest for progress tracking
            const xhr = new XMLHttpRequest();
            
            xhr.upload.addEventListener('progress', function(e) {{
                if (e.lengthComputable) {{
                    const percentComplete = (e.loaded / e.total) * 100;
                    const uploadedMB = (e.loaded / 1024 / 1024).toFixed(1);
                    const totalMB = (e.total / 1024 / 1024).toFixed(1);
                    
                    progressBar.value = percentComplete;
                    progressText.textContent = `Uploading... ${{Math.round(percentComplete)}}% (${{uploadedMB}}/${{totalMB}} MB)`;
                }} else {{
                    // For streams of unknown size (as mentioned in AWS article)
                    progressText.textContent = `Uploading... ${{(e.loaded / 1024 / 1024).toFixed(1)}} MB uploaded`;
                }}
            }});
            
            xhr.addEventListener('load', function() {{
                progressContainer.style.display = 'none';
                resultDiv.style.display = 'block';
                
                if (xhr.status === 201 || xhr.status === 204) {{
                    resultDiv.className = 'result success';
                    resultDiv.innerHTML = `
                        <strong>✅ Upload Successful!</strong><br>
                        File "${{window.sanitizedFilename}}" has been uploaded successfully.<br>
                        <small>Location: {key_prefix}${{window.sanitizedFilename || 'uploaded-file'}}</small>
                    `;
                    
                    // Reset form
                    fileInput.value = '';
                    uploadBtn.disabled = false;
                    uploadBtn.textContent = '📤 Upload Another File';
                }} else {{
                    resultDiv.className = 'result error';
                    let errorMessage = 'Upload Failed';
                    let suggestion = 'Please try again or check your file.';
                    
                    // Provide specific error guidance based on status codes
                    switch(xhr.status) {{
                        case 403:
                            errorMessage = 'Access Denied';
                            suggestion = 'The upload form may have expired or your file may be too large. Try refreshing the form or reducing file size.';
                            break;
                        case 400:
                            errorMessage = 'Bad Request';
                            suggestion = 'There may be an issue with the file format or upload parameters. Please try a different file.';
                            break;
                        case 413:
                            errorMessage = 'File Too Large';
                            suggestion = `Your file exceeds the maximum allowed size of {max_size_mb} MB. Please select a smaller file.`;
                            break;
                        case 0:
                            errorMessage = 'Network Error';
                            suggestion = 'Please check your internet connection and try again.';
                            break;
                        default:
                            if (xhr.status >= 500) {{
                                errorMessage = 'Server Error';
                                suggestion = 'There was a temporary server issue. Please try again in a few moments.';
                            }}
                    }}
                    
                    resultDiv.innerHTML = `
                        <strong>❌ ${{errorMessage}}</strong><br>
                        Status: ${{xhr.status}} ${{xhr.statusText}}<br>
                        <small>${{suggestion}}</small>
                    `;
                    uploadBtn.disabled = false;
                    uploadBtn.textContent = '📤 Upload File';
                }}
            }});
            
            xhr.addEventListener('error', function() {{
                progressContainer.style.display = 'none';
                resultDiv.style.display = 'block';
                resultDiv.className = 'result error';
                resultDiv.innerHTML = `
                    <strong>❌ Network Upload Error</strong><br>
                    A network error occurred during upload. This could be due to:<br>
                    <small>
                    • Internet connection issues<br>
                    • CORS configuration problems (if ETag header not exposed)<br>
                    • Firewall or proxy blocking the upload<br>
                    <br>
                    Please check your connection and try again.
                    </small>
                `;
                uploadBtn.disabled = false;
                uploadBtn.textContent = '📤 Upload File';
            }});
            
            xhr.open('POST', this.action);
            xhr.send(formData);
        }});
        
        // File input change handler
        document.getElementById('fileInput').addEventListener('change', function() {{
            const file = this.files[0];
            if (file) {{
                const maxSize = {max_size_mb} * 1024 * 1024;
                if (file.size > maxSize) {{
                    alert(`File size (${{(file.size / 1024 / 1024).toFixed(2)}} MB) exceeds the maximum allowed size ({max_size_mb} MB)`);
                    this.value = '';
                }}
            }}
        }});
        
        // Dynamic expiration countdown
        function startExpirationCountdown() {{
            const expiresInMinutes = {expiration_minutes};
            const expirationTime = new Date(Date.now() + (expiresInMinutes * 60 * 1000));
            const timeRemainingElement = document.getElementById('timeRemaining');
            
            function updateCountdown() {{
                const now = new Date();
                const timeLeft = expirationTime - now;
                
                if (timeLeft <= 0) {{
                    timeRemainingElement.textContent = 'EXPIRED - This upload form is no longer valid';
                    timeRemainingElement.style.color = '#dc3545';
                    document.getElementById('uploadBtn').disabled = true;
                    document.getElementById('uploadBtn').textContent = '❌ Form Expired';
                    return;
                }}
                
                const hours = Math.floor(timeLeft / (1000 * 60 * 60));
                const minutes = Math.floor((timeLeft % (1000 * 60 * 60)) / (1000 * 60));
                const seconds = Math.floor((timeLeft % (1000 * 60)) / 1000);
                
                let timeString = 'Expires in ';
                if (hours > 0) timeString += `${{hours}}h `;
                if (minutes > 0) timeString += `${{minutes}}m `;
                timeString += `${{seconds}}s`;
                
                timeRemainingElement.textContent = timeString;
                
                // Change color as expiration approaches
                if (timeLeft < 300000) {{ // Less than 5 minutes
                    timeRemainingElement.style.color = '#dc3545'; // Red
                }} else if (timeLeft < 900000) {{ // Less than 15 minutes  
                    timeRemainingElement.style.color = '#fd7e14'; // Orange
                }} else {{
                    timeRemainingElement.style.color = 'inherit';
                }}
            }}
            
            updateCountdown(); // Initial call
            setInterval(updateCountdown, 1000); // Update every second
        }}
        
        // S3 Object Key Validation
        function validateS3ObjectKey(filename) {{
            const hint = `Object Key (Filename) Limitations:

Length: A key's UTF-8 encoded name can be up to 1024 bytes long, which can be around 1024 characters.
Characters: Can contain uppercase letters, numbers, and symbols like underscores (_), dashes (-), and forward slashes (/).
Directory Segments: Each segment of a virtual directory (e.g., folder/subfolder/file.txt, each part is a segment) is limited to 255 characters.
Prefixes: An object key cannot begin with a forward slash.`;

            // Check length
            const filenameSize = new Blob([filename]).size;
            if (filenameSize > 1024) {{
                return {{
                    valid: false,
                    error: `Filename is too long (${{filenameSize}} bytes, max 1024 bytes)`,
                    hint: hint
                }};
            }}
            
            // Check for invalid characters (S3 allows most characters, but some are problematic)
            const invalidChars = /[\\x00-\\x1f\\x7f"'<>&|]/;
            if (invalidChars.test(filename)) {{
                return {{
                    valid: false,
                    error: `Filename contains invalid characters. Avoid control characters, quotes, and special symbols.`,
                    hint: hint
                }};
            }}
            
            // Check if starts with forward slash
            if (filename.startsWith('/')) {{
                return {{
                    valid: false,
                    error: `Filename cannot start with a forward slash (/)`,
                    hint: hint
                }};
            }}
            
            // Check directory segments
            const segments = filename.split('/');
            for (let segment of segments) {{
                const segmentSize = new Blob([segment]).size;
                if (segmentSize > 255) {{
                    return {{
                        valid: false,
                        error: `Directory segment '${{segment}}' is too long (${{segmentSize}} bytes, max 255 bytes per segment)`,
                        hint: hint
                    }};
                }}
            }}
            
            // Basic sanitization: replace problematic characters
            let sanitizedName = filename
                .replace(/[\\x00-\\x1f\\x7f]/g, '') // Remove control characters
                .replace(/["'<>&|]/g, '_'); // Replace problematic characters with underscore
            
            return {{
                valid: true,
                sanitizedName: sanitizedName,
                hint: hint
            }};
        }}

        // Enhanced file size validation
        function formatFileSize(bytes) {{
            if (bytes === 0) return '0 Bytes';
            const k = 1024;
            const sizes = ['Bytes', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
        }}
        
        // Start countdown when page loads
        document.addEventListener('DOMContentLoaded', function() {{
            startExpirationCountdown();
        }});
    </script>
</body>
</html>"""
    
    try:
        # Use template rendering instead of string formatting
        template_params = {
            'upload_location': key_prefix or "Root folder",
            'max_size_mb': max_size_mb,
            'post_url': presigned_post['url'],
            'hidden_fields': hidden_fields,
            'key_with_placeholder': key_prefix + "${filename}",
            'key_pattern': key_prefix + "[filename]",
            'key_prefix': key_prefix,
            'generated_time': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'),
            'expiration_minutes': expiration_minutes or 1,
            'filename_placeholder': '${filename}'  # Clean placeholder for JavaScript
        }
        
        logging.info(f"Rendering upload form template with key_prefix: {key_prefix}")
        
        # Render the template instead of using embedded HTML string
        return render_template('upload_form.html', **template_params)
        
    except Exception as e:
        logging.error(f"Error rendering upload form template: {e}")
        raise

@app.route("/save-html-file", methods=["POST"])
def save_html_file():
    """Save HTML file for pywebview environments"""
    try:
        data = request.get_json()
        html_content = data.get('html_content')
        filename = data.get('filename', 'S3-Upload-Form.html')
        
        if not html_content:
            return jsonify({"success": False, "message": "No HTML content provided"})
        
        # Try to use webview save dialog if available
        if hasattr(webview, 'windows') and webview.windows:
            try:
                # Use webview file dialog
                file_path = webview.windows[0].create_file_dialog(
                    webview.SAVE_DIALOG,
                    save_filename=filename,
                    file_types=('HTML Files (*.html)', 'All Files (*.*)')
                )
                
                if file_path:
                    with open(file_path[0], 'w', encoding='utf-8') as f:
                        f.write(html_content)
                    return jsonify({"success": True, "message": f"File saved successfully to {file_path[0]}"})
                else:
                    return jsonify({"success": False, "message": "Save cancelled by user"})
                    
            except Exception as e:
                logging.error(f"WebView save dialog failed: {e}")
                return jsonify({"success": False, "message": "Save dialog not available"})
        else:
            return jsonify({"success": False, "message": "WebView not available"})
            
    except Exception as e:
        logging.error(f"Error in save_html_file: {e}")
        return jsonify({"success": False, "message": f"Error saving file: {str(e)}"})

@app.route("/parse-presigned-url", methods=["POST"])
def parse_presigned_url():
    """Parse an existing presigned URL to extract timestamp information"""
    try:
        data = request.get_json()
        url = data.get("url")
        
        if not url:
            return jsonify({"success": False, "message": "URL is required"})

        logging.info("Parsing presigned URL for timestamp information")
        
        # Parse the URL
        parsed_url = urlparse(url)
        query_params = parse_qs(parsed_url.query)
        
        # Extract X-Amz-Date and X-Amz-Expires
        amz_date = query_params.get('X-Amz-Date', [None])[0]
        amz_expires = query_params.get('X-Amz-Expires', [None])[0]
        
        if not amz_date:
            return jsonify({"success": False, "message": "X-Amz-Date not found in URL"})
        
        if not amz_expires:
            return jsonify({"success": False, "message": "X-Amz-Expires not found in URL"})
        
        try:
            # Parse the timestamp (format: 20231215T123456Z)
            issued_at = datetime.strptime(amz_date, '%Y%m%dT%H%M%SZ')
            expires_in_seconds = int(amz_expires)
            expires_at = issued_at + timedelta(seconds=expires_in_seconds)
            
            logging.info(f"Successfully parsed presigned URL: issued at {issued_at}, expires at {expires_at}")
            
            return jsonify({
                "success": True,
                "issued_at": issued_at.isoformat(),
                "expires_at": expires_at.isoformat(),
                "expiration_seconds": expires_in_seconds,
                "is_expired": datetime.utcnow() > expires_at
            })
            
        except ValueError as ve:
            logging.error(f"Error parsing timestamp from URL: {ve}")
            return jsonify({"success": False, "message": f"Invalid timestamp format: {str(ve)}"})
    
    except Exception as e:
        logging.error(f"An unexpected error occurred parsing presigned URL: {e}")
        return jsonify({"success": False, "message": f"Error: {str(e)}"})

@app.route("/list-buckets", methods=["POST"])
def list_buckets():
    """List available S3 buckets"""
    try:
        data = request.get_json()
        access_key = data.get("access_key")
        secret_key = data.get("secret_key")
        session_token = data.get("session_token")
        region = data.get("region", "us-east-1")

        logging.info("Listing S3 buckets")

        if not access_key or not secret_key:
            logging.warning("Missing required credentials for listing buckets")
            return jsonify({"success": False, "message": "Missing required credentials"})

        # Create S3 session and client
        session_kwargs = {
            "aws_access_key_id": access_key,
            "aws_secret_access_key": secret_key,
            "region_name": region
        }
        if session_token:
            session_kwargs["aws_session_token"] = session_token

        session = boto3.Session(**session_kwargs)
        s3 = session.client("s3")

        # List buckets
        response = s3.list_buckets()
        
        buckets = []
        for bucket in response.get('Buckets', []):
            buckets.append({
                'name': bucket['Name'],
                'creation_date': bucket['CreationDate'].strftime('%Y-%m-%d %H:%M:%S')
            })

        logging.info(f"Successfully listed {len(buckets)} buckets")
        return jsonify({
            "success": True,
            "buckets": buckets
        })

    except ClientError as e:
        logging.error(f"ClientError listing buckets: {e}")
        return jsonify({"success": False, "message": f"AWS Error: {str(e)}"})
    except Exception as e:
        logging.error(f"An unexpected error occurred listing buckets: {e}")
        return jsonify({"success": False, "message": f"Error: {str(e)}"})

@app.route("/")
def index():
    """Redirect to wizard as main interface"""
    return redirect(url_for('wizard'))

@app.route("/extension-renamer", methods=["GET", "POST"])
def extension_renamer():
    if request.method == "POST":
        try:
            access_key = request.form["access_key"]
            secret_key = request.form["secret_key"]
            bucket = request.form["bucket"]
            prefix = request.form.get("prefix", "")
            old_ext = request.form["old_ext"]
            new_ext = request.form["new_ext"]
            keep_original = "keep_original" in request.form
            recursive = "recursive" in request.form

            logging.info(f"Form submission received for bucket '{bucket}' with prefix '{prefix}'.")

            # Validate extensions
            if not old_ext.startswith('.'):
                old_ext = '.' + old_ext
            if not new_ext.startswith('.'):
                new_ext = '.' + new_ext

            session = boto3.Session(
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key
            )
            s3 = session.client("s3")

            global preview_files
            preview_files = list_matching_files(s3, bucket, prefix, old_ext, recursive)
            logging.info(f"Successfully retrieved {len(preview_files)} files for preview.")

            # Save all for second phase
            app.config.update(
                S3_CLIENT=s3,
                BUCKET=bucket,
                OLD_EXT=old_ext,
                NEW_EXT=new_ext,
                KEEP_ORIGINAL=keep_original,
                RECURSIVE=recursive
            )

            return render_template("preview.html", files=preview_files, recursive=recursive)

        except NoCredentialsError:
            flash("Invalid AWS credentials provided.", "error")
            logging.error("NoCredentialsError: Invalid AWS credentials provided on form submission.")
        except ClientError as e:
            flash(f"AWS Error: {str(e)}", "error")
            logging.error(f"ClientError on form submission: {e}")
        except Exception as e:
            flash(f"Error: {str(e)}", "error")
            logging.error(f"An unexpected error occurred on form submission: {e}")

    logging.info("Rendering form.html for GET request.")
    return render_template("form.html")

@app.route("/confirm", methods=["POST"])
def confirm():
    try:
        s3 = app.config["S3_CLIENT"]
        bucket = app.config["BUCKET"]
        old_ext = app.config["OLD_EXT"]
        new_ext = app.config["NEW_EXT"]
        keep_original = app.config["KEEP_ORIGINAL"]
        recursive = app.config.get("RECURSIVE", True)

        # Get selected files from form
        selected_files = request.form.getlist("selected_files")

        logging.info(f"Confirmation received for {len(selected_files)} files in bucket '{bucket}'.")

        if not selected_files:
            logging.warning("No files selected for processing in confirmation step.")
            return render_template("result.html",
                                 success=False,
                                 message="No files were selected for processing.",
                                 recursive=recursive)

        success_count = 0
        error_count = 0
        errors = []

        for key in selected_files:
            try:
                new_key = key[:-len(old_ext)] + new_ext
                logging.info(f"Attempting to rename '{key}' to '{new_key}'.")
                s3.copy_object(Bucket=bucket, CopySource={'Bucket': bucket, 'Key': key}, Key=new_key)
                if not keep_original:
                    s3.delete_object(Bucket=bucket, Key=key)
                    logging.info(f"Successfully deleted original file '{key}'.")
                success_count += 1
                logging.info(f"Successfully processed '{key}'.")
            except ClientError as e:
                error_msg = f"Error processing {key}: {str(e)}"
                logging.error(f"ClientError: {error_msg}")
                errors.append(error_msg)
                error_count += 1
            except Exception as e:
                error_msg = f"An unexpected error occurred processing {key}: {str(e)}"
                logging.error(error_msg)
                errors.append(error_msg)
                error_count += 1

        result_message = f"Successfully processed {success_count} files."
        if error_count > 0:
            result_message += f" {error_count} files had errors."

        scan_type = "recursive" if recursive else "non-recursive"
        result_message += f" (Scanned using {scan_type} mode)"

        logging.info(f"Processing complete. {result_message}")
        return render_template("result.html",
                             success=True,
                             message=result_message,
                             success_count=success_count,
                             error_count=error_count,
                             errors=errors,
                             recursive=recursive)

    except Exception as e:
        logging.error(f"An unexpected error occurred during confirmation: {e}")
        return render_template("result.html",
                             success=False,
                             message=f"Error: {str(e)}",
                             recursive=recursive)

def start_flask_app(port):
    """Start the Flask application in a separate thread."""
    app.run(debug=False, host='127.0.0.1', port=port, use_reloader=False)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="S3 Extension Renamer")
    parser.add_argument("--port", type=int, default=5000, help="Port to run the web server on.")
    parser.add_argument("--web", action="store_true", help="Run as web app instead of desktop app (pywebview)")
    args = parser.parse_args()
    
    # Ensure the lock file is removed on exit
    atexit.register(remove_lock_file)

    # Check for lock file to prevent multiple instances
    if os.path.exists(LOCK_FILE):
        show_popup(
            "Application Already Running",
            "S3 Extension Renamer is already running.\n\n"
            "Please close the existing instance first."
        )
        sys.exit(0)

    # Find a free port
    port = find_free_port(args.port)
    if port is None:
        show_popup(
            "No Available Ports",
            f"Could not find an available port starting from {args.port}.\n\n"
            "Please close other applications and try again."
        )
        sys.exit(1)

    # Create lock file
    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))

    # Ensure templates and static directories exist
    if not os.path.exists(template_folder):
        logging.warning(f"Templates directory not found at: {template_folder}")
        print(f"WARNING: templates directory not found at: {template_folder}")
    if not os.path.exists(static_folder):
        logging.warning(f"Static directory not found at: {static_folder}")
        print(f"WARNING: static directory not found at: {static_folder}")

    logging.info("Starting S3 Extension Renamer...")
    logging.info(f"Templates folder: {template_folder}")
    logging.info(f"Static folder: {static_folder}")
    logging.info(f"Using port: {port}")
    
    # Start Flask in a separate thread
    flask_thread = threading.Thread(target=start_flask_app, args=(port,))
    flask_thread.daemon = True
    flask_thread.start()
    
    # Give Flask a moment to start
    time.sleep(1)
    
    if args.web:
        # Run as web application
        logging.info(f"Starting web application on http://127.0.0.1:{port}")
        print(f"\n🌐 S3 Extension Renamer is running at: http://127.0.0.1:{port}")
        print("📝 Note: In web mode, credentials are stored in browser session storage")
        print("🛑 Press Ctrl+C to stop the server\n")
        
        try:
            # Keep the main thread alive
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logging.info("Web server stopped by user")
            print("\n👋 Server stopped. Goodbye!")
    else:
        # Run as desktop application with pywebview
        logging.info("Creating desktop window...")
        webview.create_window(
            'S3 Extension Renamer',
            f'http://127.0.0.1:{port}',
            width=1200,
            height=800,
            min_size=(800, 600),
            resizable=True
        )
        
        webview.start(debug=False)

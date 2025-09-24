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
import sys
import atexit
import socket
import argparse
import webview
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs
import re
import zipfile
import io
import secrets
import hashlib
import base64
from flask import Response
import tkinter as tk
from tkinter import messagebox

LOCK_FILE = "app.lock"

def remove_lock_file():
    """Remove the lock file on exit."""
    if os.path.exists(LOCK_FILE):
        os.remove(LOCK_FILE)
        logging.info("Lock file removed.")

def show_popup(title, message):
    """Show a popup window with the given title and message."""
    messagebox.showinfo(title, message)

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

# Secure session store for AWS credentials
# In production, use Redis or a proper database
session_store = {}

class SecureSession:
    def __init__(self):
        self.sessions = {}
        self.session_timeout = 3600  # 1 hour timeout

    def create_session(self, credentials):
        """Create a secure session with AWS credentials"""
        session_id = secrets.token_urlsafe(32)
        session_data = {
            'credentials': credentials,
            'created_at': datetime.now(),
            'last_accessed': datetime.now()
        }
        self.sessions[session_id] = session_data
        logging.info(f"Created secure session: {session_id[:8]}...")
        return session_id

    def get_credentials(self, session_id):
        """Get AWS credentials for a session"""
        if not session_id or session_id not in self.sessions:
            return None
        
        session_data = self.sessions[session_id]
        
        # Check if session has expired
        if (datetime.now() - session_data['last_accessed']).seconds > self.session_timeout:
            self.invalidate_session(session_id)
            return None
        
        # Update last accessed time
        session_data['last_accessed'] = datetime.now()
        return session_data['credentials']

    def invalidate_session(self, session_id):
        """Remove a session"""
        if session_id in self.sessions:
            del self.sessions[session_id]
            logging.info(f"Invalidated session: {session_id[:8]}...")

    def cleanup_expired_sessions(self):
        """Remove expired sessions"""
        current_time = datetime.now()
        expired_sessions = []
        
        for session_id, session_data in self.sessions.items():
            if (current_time - session_data['last_accessed']).seconds > self.session_timeout:
                expired_sessions.append(session_id)
        
        for session_id in expired_sessions:
            self.invalidate_session(session_id)

# Global session manager
session_manager = SecureSession()

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
    """Browse folders/prefixes in S3 bucket using secure session"""
    try:
        data = request.get_json()
        bucket = data.get("bucket")
        current_prefix = data.get("prefix", "")

        logging.info(f"Browsing folders for bucket '{bucket}' with prefix '{current_prefix}'")

        # Get credentials from secure session
        credentials = get_session_credentials(data)
        if not credentials:
            logging.warning("Invalid or missing session for browsing folders")
            return jsonify({"success": False, "message": "Invalid or expired session"}), 401

        if not bucket:
            logging.warning("Missing bucket parameter for browsing folders")
            return jsonify({"success": False, "message": "Missing bucket parameter"})

        # Create S3 session and client using stored credentials
        session_kwargs = {
            "aws_access_key_id": credentials["access_key"],
            "aws_secret_access_key": credentials["secret_key"],
            "region_name": credentials["region"]
        }
        if credentials.get("session_token"):
            session_kwargs["aws_session_token"] = credentials["session_token"]

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

@app.route("/multi-upload")
def multi_upload():
    """Multi-type file upload interface"""
    logging.info("Rendering multi-upload interface")
    return render_template("multi_upload_form.html")

@app.route("/generate-presigned-url", methods=["POST"])
def generate_presigned_url():
    """Generate pre-signed URL for S3 upload using secure session"""
    try:
        data = request.get_json()
        bucket = data.get("bucket")
        object_key = data.get("object_key")
        url_type = data.get("url_type", "upload")  # Default to upload
        generate_html = data.get("generate_html", False)  # Generate HTML form
        upload_html = data.get("upload_html", False)  # Upload HTML form to S3
        expiration = int(data.get("expiration", 3600))  # Default 1 hour
        content_type = data.get("content_type")
        use_timestamp_prefix = data.get("use_timestamp_prefix", True)  # Add timestamp subfolder by default

        logging.info(f"Generating presigned URL for bucket '{bucket}', key '{object_key}'")

        # Get credentials from secure session
        credentials = get_session_credentials(data)
        if not credentials:
            logging.warning("Invalid or missing session for presigned URL generation")
            return jsonify({"success": False, "message": "Invalid or expired session"}), 401
        
        if url_type == "download" and not object_key:
            logging.warning("Missing object_key for download URL")
            return jsonify({"success": False, "message": "Object key is required for download URLs"})
        
        # For upload URLs, object_key can be empty (uploads to root)
        if object_key is None:
            object_key = ""

        # Create S3 session and client using stored credentials
        session_kwargs = {
            "aws_access_key_id": credentials["access_key"],
            "aws_secret_access_key": credentials["secret_key"],
            "region_name": credentials["region"]
        }
        if credentials.get("session_token"):
            session_kwargs["aws_session_token"] = credentials["session_token"]

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
            
            # Optionally generate timestamp-based subfolder to avoid filename conflicts
            if use_timestamp_prefix:
                timestamp_folder = datetime.now().strftime('%Y%m%d-%H%M%S')
                timestamp_key_prefix = html_key_prefix + timestamp_folder + "/"
            else:
                timestamp_key_prefix = html_key_prefix
            
            # Enhanced policy for multiple file uploads:
            # 1. Allow any filename after the prefix
            conditions.append(["starts-with", "$key", timestamp_key_prefix])
            # 2. Add content-length-range for individual file size limits
            max_file_size = 5 * 1024 * 1024 * 1024  # 5GB max per file (S3 single upload limit)
            conditions.append(["content-length-range", 1, max_file_size])
            # 3. Set a template key that will be replaced in the HTML form
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
                    "issued_at": datetime.now().isoformat(),
                    "expires_at": (datetime.now() + timedelta(seconds=expiration)).isoformat(),
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
                issued_at = datetime.now()
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
                            expires_at=expires_at,
                            expiration_minutes=expiration // 60,
                            max_size_mb=5120,  # Default 5GB limit (S3 single upload maximum)
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
                            html_filename = f"upload-form-{datetime.now().strftime('%Y%m%d-%H%M%S')}.html"
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

def generate_upload_html(presigned_post, key_prefix, expires_at, expiration_minutes, max_size_mb=100, add_timestamp=True):
    """Generate a standalone HTML upload form using template
    
    Args:
        presigned_post: The presigned POST data from S3
        key_prefix: The S3 key prefix (may already include timestamp)
        expires_at: The actual expiration datetime of the presigned URL
        expiration_minutes: How long the form is valid (for backward compatibility)
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
            'generated_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'expiration_minutes': expiration_minutes or 1,
            'expires_at_iso': expires_at.isoformat() if expires_at else None,
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

@app.route("/generate-multi-presigned-posts", methods=["POST"])
def generate_multi_presigned_posts():
    """Generate multiple pre-signed POST URLs with file matching rules"""
    try:
        data = request.get_json()
        access_key = data.get("access_key")
        secret_key = data.get("secret_key")
        session_token = data.get("session_token")
        region = data.get("region", "us-east-1")
        bucket = data.get("bucket")
        base_prefix = data.get("base_prefix", "")  # Base folder path
        expiration = int(data.get("expiration", 3600))  # Default 1 hour
        use_timestamp_prefix = data.get("use_timestamp_prefix", True)
        
        # Array of file type configurations
        file_configs = data.get("file_configs", [])
        
        logging.info(f"Generating multiple presigned POST URLs for bucket '{bucket}' with {len(file_configs)} file type configs")

        if not access_key or not secret_key or not bucket:
            logging.warning("Missing required credentials for multi-presigned URL generation")
            return jsonify({"success": False, "message": "Missing required credentials (access_key, secret_key, bucket)"})
        
        if not file_configs:
            logging.warning("No file configurations provided")
            return jsonify({"success": False, "message": "At least one file_config is required"})

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

        # Generate timestamp folder if requested
        timestamp_folder = ""
        if use_timestamp_prefix:
            timestamp_folder = datetime.now().strftime('%Y%m%d-%H%M%S') + "/"

        presigned_configs = []
        
        for config in file_configs:
            label = config.get("label", "files")
            match_rules = config.get("match", {})
            content_type_prefix = config.get("content_type_prefix")  # Optional: enforce content type in policy
            max_size_mb = config.get("max_size_mb", 5120)  # Default 5GB per file (S3 single upload limit)
            
            # Build the key prefix for this file type
            file_type_prefix = base_prefix
            if file_type_prefix and not file_type_prefix.endswith('/'):
                file_type_prefix += '/'
            file_type_prefix += timestamp_folder
            
            # If label is provided, add it as a subfolder
            if label and label != "files":
                file_type_prefix += f"{label}/"
            
            # Prepare conditions for this file type
            conditions = []
            fields = {}
            
            # Key prefix condition - allow any filename after the prefix
            conditions.append(["starts-with", "$key", file_type_prefix])
            
            # File size limit
            max_file_size = max_size_mb * 1024 * 1024
            conditions.append(["content-length-range", 1, max_file_size])
            
            # Optional: Content-Type enforcement in policy
            if content_type_prefix:
                conditions.append(["starts-with", "$Content-Type", content_type_prefix])
                
            # Generate presigned POST for this file type
            try:
                response = s3.generate_presigned_post(
                    Bucket=bucket,
                    Key=file_type_prefix + "${filename}",  # Template key
                    Fields=fields,
                    Conditions=conditions,
                    ExpiresIn=expiration
                )
                
                # Build the presigned config in the format expected by frontend
                presigned_config = {
                    "label": label,
                    "match": match_rules,
                    "url": response["url"],
                    "fields": response["fields"].copy()
                }
                
                # Set key field to empty (frontend will set it dynamically)
                presigned_config["fields"]["key"] = ""
                
                presigned_configs.append(presigned_config)
                
                logging.info(f"Generated presigned POST for '{label}' file type with prefix '{file_type_prefix}'")
                
            except ClientError as e:
                logging.error(f"Failed to generate presigned POST for '{label}': {e}")
                return jsonify({"success": False, "message": f"Failed to generate presigned POST for '{label}': {str(e)}"})

        # Calculate timestamps  
        issued_at = datetime.now()
        expires_at = issued_at + timedelta(seconds=expiration)

        logging.info(f"Successfully generated {len(presigned_configs)} presigned POST configurations")
        
        return jsonify({
            "success": True,
            "presigned_configs": presigned_configs,
            "base_prefix": base_prefix,
            "timestamp_folder": timestamp_folder,
            "issued_at": issued_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "expiration_seconds": expiration
        })

    except Exception as e:
        logging.error(f"An unexpected error occurred generating multi-presigned URLs: {e}")
        return jsonify({"success": False, "message": f"Error: {str(e)}"})

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
    """List available S3 buckets using secure session"""
    try:
        data = request.get_json()
        logging.info("Listing S3 buckets")

        # Get credentials from secure session
        credentials = get_session_credentials(data)
        if not credentials:
            logging.warning("Invalid or missing session for listing buckets")
            return jsonify({"success": False, "message": "Invalid or expired session"}), 401

        # Create S3 session and client using stored credentials
        session_kwargs = {
            "aws_access_key_id": credentials["access_key"],
            "aws_secret_access_key": credentials["secret_key"],
            "region_name": credentials["region"]
        }
        if credentials.get("session_token"):
            session_kwargs["aws_session_token"] = credentials["session_token"]

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

@app.route("/s3-delete-object", methods=["POST"])
def s3_delete_object():
    """Delete an S3 object"""
    try:
        data = request.get_json()
        bucket = data.get("bucket")
        key = data.get("key")

        logging.info(f"Deleting object '{key}' from bucket '{bucket}'")

        # Get credentials from secure session
        credentials = get_session_credentials(data)
        if not credentials:
            logging.warning("Invalid or missing session for object deletion")
            return jsonify({"success": False, "message": "Invalid or expired session"}), 401

        if not bucket or not key:
            logging.warning("Missing required parameters for object deletion")
            return jsonify({"success": False, "message": "Missing required parameters"})

        # Create S3 session and client using stored credentials
        session_kwargs = {
            "aws_access_key_id": credentials["access_key"],
            "aws_secret_access_key": credentials["secret_key"],
            "region_name": credentials["region"]
        }
        if credentials.get("session_token"):
            session_kwargs["aws_session_token"] = credentials["session_token"]

        session = boto3.Session(**session_kwargs)
        s3 = session.client("s3")

        # Delete the object
        s3.delete_object(Bucket=bucket, Key=key)
        
        logging.info(f"Successfully deleted object '{key}' from bucket '{bucket}'")
        return jsonify({
            "success": True,
            "message": f"Successfully deleted {key}"
        })

    except ClientError as e:
        logging.error(f"ClientError deleting object: {e}")
        return jsonify({"success": False, "message": f"AWS Error: {str(e)}"})
    except Exception as e:
        logging.error(f"An unexpected error occurred deleting object: {e}")
        return jsonify({"success": False, "message": f"Error: {str(e)}"})

@app.route("/s3-delete-folder", methods=["POST"])
def s3_delete_folder():
    """Delete all objects with a given prefix (folder)"""
    try:
        data = request.get_json()
        bucket = data.get("bucket")
        prefix = data.get("prefix")

        logging.info(f"Deleting folder with prefix '{prefix}' from bucket '{bucket}'")

        # Get credentials from secure session
        credentials = get_session_credentials(data)
        if not credentials:
            logging.warning("Invalid or missing session for folder deletion")
            return jsonify({"success": False, "message": "Invalid or expired session"}), 401

        if not bucket or not prefix:
            logging.warning("Missing required parameters for folder deletion")
            return jsonify({"success": False, "message": "Missing required parameters"})

        session_kwargs = {
            "aws_access_key_id": credentials["access_key"],
            "aws_secret_access_key": credentials["secret_key"],
            "region_name": credentials["region"]
        }
        if credentials.get("session_token"):
            session_kwargs["aws_session_token"] = credentials["session_token"]

        session = boto3.Session(**session_kwargs)
        s3 = session.client("s3")

        # List all objects with the given prefix
        paginator = s3.get_paginator("list_objects_v2")
        objects_to_delete = []
        
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            if "Contents" in page:
                for obj in page["Contents"]:
                    objects_to_delete.append({"Key": obj["Key"]})

        if not objects_to_delete:
            logging.info(f"No objects found with prefix '{prefix}'")
            return jsonify({
                "success": True,
                "message": f"No objects found with prefix {prefix}",
                "deleted_count": 0
            })

        # Delete objects in batches (S3 allows up to 1000 objects per batch)
        deleted_count = 0
        for i in range(0, len(objects_to_delete), 1000):
            batch = objects_to_delete[i:i+1000]
            
            response = s3.delete_objects(
                Bucket=bucket,
                Delete={
                    'Objects': batch,
                    'Quiet': False
                }
            )
            
            # Count successful deletions
            if 'Deleted' in response:
                deleted_count += len(response['Deleted'])
            
            # Log any errors
            if 'Errors' in response:
                for error in response['Errors']:
                    logging.error(f"Error deleting {error['Key']}: {error['Message']}")

        logging.info(f"Successfully deleted {deleted_count} objects with prefix '{prefix}' from bucket '{bucket}'")
        return jsonify({
            "success": True,
            "message": f"Successfully deleted {deleted_count} objects",
            "deleted_count": deleted_count
        })

    except ClientError as e:
        logging.error(f"ClientError deleting folder: {e}")
        return jsonify({"success": False, "message": f"AWS Error: {str(e)}"})
    except Exception as e:
        logging.error(f"An unexpected error occurred deleting folder: {e}")
        return jsonify({"success": False, "message": f"Error: {str(e)}"})

@app.route("/s3-create-folder", methods=["POST"])
def s3_create_folder():
    """Create a folder (empty object with trailing slash) in S3"""
    try:
        data = request.get_json()
        bucket = data.get("bucket")
        folder_key = data.get("folder_key")

        logging.info(f"Creating folder '{folder_key}' in bucket '{bucket}'")

        # Get credentials from secure session
        credentials = get_session_credentials(data)
        if not credentials:
            logging.warning("Invalid or missing session for folder creation")
            return jsonify({"success": False, "message": "Invalid or expired session"}), 401

        if not bucket or not folder_key:
            logging.warning("Missing required parameters for folder creation")
            return jsonify({"success": False, "message": "Missing required parameters"})

        # Ensure folder key ends with slash
        if not folder_key.endswith('/'):
            folder_key += '/'

        session_kwargs = {
            "aws_access_key_id": credentials["access_key"],
            "aws_secret_access_key": credentials["secret_key"],
            "region_name": credentials["region"]
        }
        if credentials.get("session_token"):
            session_kwargs["aws_session_token"] = credentials["session_token"]

        session = boto3.Session(**session_kwargs)
        s3 = session.client("s3")

        # Create empty object with trailing slash to represent folder
        s3.put_object(
            Bucket=bucket,
            Key=folder_key,
            Body=b'',
            ContentLength=0
        )
        
        logging.info(f"Successfully created folder '{folder_key}' in bucket '{bucket}'")
        return jsonify({
            "success": True,
            "message": f"Successfully created folder {folder_key}",
            "folder_key": folder_key
        })

    except ClientError as e:
        logging.error(f"ClientError creating folder: {e}")
        return jsonify({"success": False, "message": f"AWS Error: {str(e)}"})
    except Exception as e:
        logging.error(f"An unexpected error occurred creating folder: {e}")
        return jsonify({"success": False, "message": f"Error: {str(e)}"})

@app.route("/s3-download-zip", methods=["POST"])
def s3_download_zip():
    """Download multiple S3 objects as a ZIP file"""
    try:
        data = request.get_json()
        bucket = data.get("bucket")
        keys = data.get("keys", [])

        logging.info(f"Creating ZIP download for {len(keys)} objects from bucket '{bucket}'")

        # Get credentials from secure session
        credentials = get_session_credentials(data)
        if not credentials:
            logging.warning("Invalid or missing session for ZIP download")
            return jsonify({"success": False, "message": "Invalid or expired session"}), 401

        if not bucket or not keys:
            logging.warning("Missing required parameters for ZIP download")
            return jsonify({"success": False, "message": "Missing required parameters"}), 400

        # Create S3 session and client using stored credentials
        session_kwargs = {
            "aws_access_key_id": credentials["access_key"],
            "aws_secret_access_key": credentials["secret_key"],
            "region_name": credentials["region"]
        }
        if credentials.get("session_token"):
            session_kwargs["aws_session_token"] = credentials["session_token"]

        session = boto3.Session(**session_kwargs)
        s3 = session.client("s3")

        # Create ZIP file in memory
        zip_buffer = io.BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for key in keys:
                # Skip None or empty keys
                if not key:
                    logging.warning(f"Skipping invalid key: {key}")
                    continue
                    
                try:
                    # Download object from S3
                    response = s3.get_object(Bucket=bucket, Key=key)
                    object_data = response['Body'].read()
                    
                    # Add to ZIP with proper filename (remove path prefixes if needed)
                    filename = key.split('/')[-1] if '/' in key else key
                    
                    # Handle folders (objects ending with /)
                    if key.endswith('/'):
                        # Skip folder markers in ZIP
                        continue
                    
                    zip_file.writestr(filename, object_data)
                    logging.info(f"Added '{key}' to ZIP as '{filename}'")
                    
                except ClientError as e:
                    logging.error(f"Error downloading object '{key}': {e}")
                    # Add error file to ZIP to inform user
                    error_content = f"Error downloading {key}: {str(e)}"
                    safe_key = str(key).replace('/', '_') if key else 'unknown'
                    zip_file.writestr(f"ERROR_{safe_key}.txt", error_content)
                except Exception as e:
                    logging.error(f"Unexpected error downloading object '{key}': {e}")
                    error_content = f"Unexpected error downloading {key}: {str(e)}"
                    safe_key = str(key).replace('/', '_') if key else 'unknown'
                    zip_file.writestr(f"ERROR_{safe_key}.txt", error_content)

        zip_buffer.seek(0)
        
        # Generate filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        zip_filename = f"s3_files_{bucket}_{timestamp}.zip"
        
        logging.info(f"ZIP file created successfully with {len(keys)} objects")
        
        # Return ZIP file as response
        return Response(
            zip_buffer.getvalue(),
            mimetype='application/zip',
            headers={
                'Content-Disposition': f'attachment; filename={zip_filename}',
                'Content-Length': str(len(zip_buffer.getvalue()))
            }
        )

    except ClientError as e:
        logging.error(f"ClientError creating ZIP download: {e}")
        return jsonify({"success": False, "message": f"AWS Error: {str(e)}"}), 500
    except Exception as e:
        logging.error(f"An unexpected error occurred creating ZIP download: {e}")
        return jsonify({"success": False, "message": f"Error: {str(e)}"}), 500

@app.route("/s3-check-file", methods=["POST"])
def s3_check_file():
    """Check if S3 file exists and get its size"""
    try:
        data = request.get_json()
        bucket = data.get("bucket")
        key = data.get("key")

        logging.info(f"Checking file '{key}' in bucket '{bucket}'")

        # Get credentials from secure session
        credentials = get_session_credentials(data)
        if not credentials:
            logging.warning("Invalid or missing session for file check")
            return jsonify({"success": False, "message": "Invalid or expired session"}), 401

        if not bucket or not key:
            logging.warning("Missing required parameters for file check")
            return jsonify({"success": False, "message": "Missing required parameters"})

        # Create S3 session and client using stored credentials
        session_kwargs = {
            "aws_access_key_id": credentials["access_key"],
            "aws_secret_access_key": credentials["secret_key"],
            "region_name": credentials["region"]
        }
        if credentials.get("session_token"):
            session_kwargs["aws_session_token"] = credentials["session_token"]

        session = boto3.Session(**session_kwargs)
        s3 = session.client("s3")

        try:
            # Use head_object to check existence and get metadata
            response = s3.head_object(Bucket=bucket, Key=key)
            
            logging.info(f"File '{key}' exists with size {response['ContentLength']}")
            return jsonify({
                "success": True,
                "exists": True,
                "size": response['ContentLength'],
                "last_modified": response['LastModified'].isoformat(),
                "etag": response.get('ETag', '').strip('"')
            })
            
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey' or e.response['Error']['Code'] == '404':
                logging.info(f"File '{key}' does not exist")
                return jsonify({
                    "success": True,
                    "exists": False,
                    "size": None
                })
            else:
                logging.error(f"Error checking file '{key}': {e}")
                return jsonify({"success": False, "message": f"Error checking file: {str(e)}"})

    except Exception as e:
        logging.error(f"An unexpected error occurred checking file: {e}")
        return jsonify({"success": False, "message": f"Error: {str(e)}"})

@app.route("/s3-search-file", methods=["POST"])
def s3_search_file():
    """Search for files with same name and size in bucket"""
    try:
        data = request.get_json()
        bucket = data.get("bucket")
        filename = data.get("filename")
        expected_size = data.get("expected_size")

        logging.info(f"Searching for file '{filename}' with size {expected_size} in bucket '{bucket}'")

        # Get credentials from secure session
        credentials = get_session_credentials(data)
        if not credentials:
            logging.warning("Invalid or missing session for file search")
            return jsonify({"success": False, "message": "Invalid or expired session"}), 401

        if not bucket or not filename:
            return jsonify({"success": False, "message": "Missing required parameters"})

        # Create S3 session and client using stored credentials
        session_kwargs = {
            "aws_access_key_id": credentials["access_key"],
            "aws_secret_access_key": credentials["secret_key"],
            "region_name": credentials["region"]
        }
        if credentials.get("session_token"):
            session_kwargs["aws_session_token"] = credentials["session_token"]

        session = boto3.Session(**session_kwargs)
        s3 = session.client("s3")

        # Search for files with matching name
        matching_files = []
        
        try:
            paginator = s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=bucket):
                for obj in page.get("Contents", []):
                    obj_filename = obj["Key"].split('/')[-1]  # Get filename from full path
                    if obj_filename == filename:
                        matching_files.append({
                            "key": obj["Key"],
                            "size": obj["Size"],
                            "last_modified": obj["LastModified"].isoformat(),
                            "size_matches": obj["Size"] == expected_size
                        })
            
            logging.info(f"Found {len(matching_files)} files matching '{filename}'")
            return jsonify({
                "success": True,
                "matches": matching_files
            })
            
        except Exception as e:
            logging.error(f"Error searching for file '{filename}': {e}")
            return jsonify({"success": False, "message": f"Error searching: {str(e)}"})

    except Exception as e:
        logging.error(f"An unexpected error occurred searching for file: {e}")
        return jsonify({"success": False, "message": f"Error: {str(e)}"})

# Authentication endpoints
@app.route("/auth/login", methods=["POST"])
def auth_login():
    """Authenticate user and create secure session"""
    # Disable request logging for this sensitive endpoint
    app.logger.disabled = True
    try:
        data = request.get_json()
        
        # Check if payload is encrypted
        is_encrypted = data.get("encrypted", False)
        
        if is_encrypted:
            # Decrypt multi-layer obfuscated credentials
            def deobfuscate_string(obfuscated_str):
                try:
                    # Layer 3: Remove timestamp prefix
                    decoded_with_timestamp = base64.b64decode(obfuscated_str).decode('utf-8')
                    if ':' in decoded_with_timestamp:
                        timestamp, encoded_str = decoded_with_timestamp.split(':', 1)
                    else:
                        encoded_str = decoded_with_timestamp
                    
                    # Layer 2: Base64 decode
                    reversed_str = base64.b64decode(encoded_str).decode('utf-8')
                    
                    # Layer 1: Reverse the string back
                    original_str = reversed_str[::-1]
                    
                    return original_str
                except Exception as e:
                    raise ValueError(f"Failed to deobfuscate: {e}")
            
            try:
                access_key = deobfuscate_string(data.get("access_key", ""))
                secret_key = deobfuscate_string(data.get("secret_key", ""))
                session_token = deobfuscate_string(data.get("session_token", "")) if data.get("session_token") else None
                region = data.get("region", "us-east-1")
                logging.info("🔐 Received encrypted authentication request")
            except Exception as e:
                logging.error(f"Failed to decrypt credentials: {e}")
                return jsonify({"success": False, "message": "Invalid encrypted credentials"}), 400
        else:
            # Handle legacy unencrypted requests
            access_key = data.get("access_key")
            secret_key = data.get("secret_key")
            session_token = data.get("session_token")
            region = data.get("region", "us-east-1")
            logging.warning("Received unencrypted authentication request - this is less secure")

        if not access_key or not secret_key:
            return jsonify({"success": False, "message": "Access key and secret key are required"}), 400

        # Test credentials by making a simple AWS call
        try:
            session_kwargs = {
                "aws_access_key_id": access_key,
                "aws_secret_access_key": secret_key,
                "region_name": region
            }
            if session_token:
                session_kwargs["aws_session_token"] = session_token

            test_session = boto3.Session(**session_kwargs)
            sts = test_session.client("sts")
            
            # Verify credentials with a simple call
            identity = sts.get_caller_identity()
            
            # Credentials are valid, create secure session
            credentials = {
                "access_key": access_key,
                "secret_key": secret_key,
                "session_token": session_token,
                "region": region
            }
            
            session_id = session_manager.create_session(credentials)
            
            logging.info(f"User authenticated successfully: {identity.get('Arn', 'Unknown')}")
            
            return jsonify({
                "success": True,
                "session_id": session_id,
                "message": "Authentication successful",
                "user_info": {
                    "account": identity.get('Account'),
                    "arn": identity.get('Arn'),
                    "user_id": identity.get('UserId')
                }
            })

        except ClientError as e:
            logging.warning(f"Authentication failed: {e}")
            return jsonify({"success": False, "message": "Invalid AWS credentials"}), 401

    except Exception as e:
        logging.error(f"Login error: {e}")
        return jsonify({"success": False, "message": "Authentication failed"}), 500
    finally:
        # Re-enable request logging for other endpoints
        app.logger.disabled = False

@app.route("/auth/logout", methods=["POST"])
def auth_logout():
    """Invalidate user session"""
    try:
        data = request.get_json() or {}
        session_id = data.get("session_id") or request.headers.get("X-Session-ID")
        
        if session_id:
            session_manager.invalidate_session(session_id)
            return jsonify({"success": True, "message": "Logged out successfully"})
        else:
            return jsonify({"success": True, "message": "No active session"})

    except Exception as e:
        logging.error(f"Logout error: {e}")
        return jsonify({"success": False, "message": "Logout failed"}), 500

@app.route("/auth/validate", methods=["POST"])
def auth_validate():
    """Validate session and return user info"""
    try:
        data = request.get_json() or {}
        session_id = data.get("session_id") or request.headers.get("X-Session-ID")
        
        if not session_id:
            return jsonify({"success": False, "message": "No session provided"}), 401
        
        credentials = session_manager.get_credentials(session_id)
        if not credentials:
            return jsonify({"success": False, "message": "Invalid or expired session"}), 401
        
        return jsonify({"success": True, "message": "Session valid"})

    except Exception as e:
        logging.error(f"Session validation error: {e}")
        return jsonify({"success": False, "message": "Validation failed"}), 500

def get_session_credentials(request_data):
    """Helper function to get credentials from session"""
    session_id = request_data.get("session_id")
    if not session_id:
        return None
    
    credentials = session_manager.get_credentials(session_id)
    if not credentials:
        return None
    
    return credentials

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

@app.route("/wizard/extension-renamer", methods=["POST"])
def wizard_extension_renamer():
    """Wizard-specific endpoint for extension renamer that returns JSON data"""
    try:
        # Handle both form data and JSON data
        if request.content_type == 'application/json':
            data = request.get_json()
            
            # Get credentials from secure session
            credentials = get_session_credentials(data)
            if not credentials:
                logging.warning("Invalid or missing session for extension renamer")
                return jsonify({"success": False, "message": "Invalid or expired session"}), 401
            
            bucket = data.get("bucket")
            prefix = data.get("prefix", "")
            old_ext = data.get("old_ext")
            new_ext = data.get("new_ext")
            keep_original = data.get("keep_original", False)
            recursive = data.get("recursive", True)
        else:
            # Form submission still uses old method for backward compatibility
            access_key = request.form["access_key"]
            secret_key = request.form["secret_key"]
            session_token = request.form.get("session_token")
            region = request.form.get("region", "us-east-1")
            bucket = request.form["bucket"]
            prefix = request.form.get("prefix", "")
            old_ext = request.form["old_ext"]
            
            # Create credentials object for form submissions
            credentials = {
                "access_key": access_key,
                "secret_key": secret_key,
                "session_token": session_token,
                "region": region
            }
            new_ext = request.form["new_ext"]
            keep_original = "keep_original" in request.form
            recursive = "recursive" in request.form

        logging.info(f"Wizard extension renamer request for bucket '{bucket}' with prefix '{prefix}'.")

        # Validate required fields
        if not credentials["access_key"] or not credentials["secret_key"] or not bucket or not old_ext or not new_ext:
            return jsonify({
                "success": False,
                "message": "Missing required fields: credentials, bucket, old_ext, new_ext"
            })

        # Validate extensions
        if not old_ext.startswith('.'):
            old_ext = '.' + old_ext
        if not new_ext.startswith('.'):
            new_ext = '.' + new_ext

        # Create S3 session using stored credentials
        session_kwargs = {
            "aws_access_key_id": credentials["access_key"],
            "aws_secret_access_key": credentials["secret_key"],
            "region_name": credentials["region"]
        }
        if credentials.get("session_token"):
            session_kwargs["aws_session_token"] = credentials["session_token"]

        session = boto3.Session(**session_kwargs)
        s3 = session.client("s3")

        # Get matching files
        matching_files = list_matching_files(s3, bucket, prefix, old_ext, recursive)
        logging.info(f"Wizard: Successfully retrieved {len(matching_files)} files for preview.")

        return jsonify({
            "success": True,
            "files": matching_files,
            "file_count": len(matching_files),
            "config": {
                "bucket": bucket,
                "prefix": prefix,
                "old_ext": old_ext,
                "new_ext": new_ext,
                "keep_original": keep_original,
                "recursive": recursive
            }
        })

    except NoCredentialsError:
        logging.error("Wizard: NoCredentialsError - Invalid AWS credentials provided.")
        return jsonify({
            "success": False,
            "message": "Invalid AWS credentials provided."
        })
    except ClientError as e:
        logging.error(f"Wizard: ClientError - {e}")
        return jsonify({
            "success": False,
            "message": f"AWS Error: {str(e)}"
        })
    except Exception as e:
        logging.error(f"Wizard: Unexpected error - {e}")
        return jsonify({
            "success": False,
            "message": f"Error: {str(e)}"
        })

@app.route("/wizard/extension-renamer/execute", methods=["POST"])
def wizard_extension_renamer_execute():
    """Execute the extension rename operation from the wizard"""
    try:
        data = request.get_json()
        
        # Get configuration and selected files
        config = data.get("config", {})
        selected_files = data.get("selected_files", [])
        
        if not selected_files:
            return jsonify({
                "success": False,
                "message": "No files selected for processing."
            })
        
        # Get credentials from secure session
        credentials = get_session_credentials(config)
        if not credentials:
            logging.warning("Invalid or missing session for extension renamer execute")
            return jsonify({"success": False, "message": "Invalid or expired session"}), 401
        
        # Extract configuration
        bucket = config.get("bucket")
        old_ext = config.get("old_ext")
        new_ext = config.get("new_ext")
        keep_original = config.get("keep_original", False)
        
        if not all([bucket, old_ext, new_ext]):
            return jsonify({
                "success": False,
                "message": "Missing required configuration parameters."
            })
        
        logging.info(f"Wizard: Executing rename operation on {len(selected_files)} files in bucket '{bucket}'.")
        
        # Create S3 session using stored credentials
        session_kwargs = {
            "aws_access_key_id": credentials["access_key"],
            "aws_secret_access_key": credentials["secret_key"],
            "region_name": credentials["region"]
        }
        if credentials.get("session_token"):
            session_kwargs["aws_session_token"] = credentials["session_token"]
            
        session = boto3.Session(**session_kwargs)
        s3 = session.client("s3")
        
        # Process each selected file
        success_count = 0
        error_count = 0
        errors = []
        
        for key in selected_files:
            try:
                new_key = key[:-len(old_ext)] + new_ext
                logging.info(f"Wizard: Attempting to rename '{key}' to '{new_key}'.")
                
                # Copy to new key
                s3.copy_object(Bucket=bucket, CopySource={'Bucket': bucket, 'Key': key}, Key=new_key)
                
                # Delete original if not keeping it
                if not keep_original:
                    s3.delete_object(Bucket=bucket, Key=key)
                    logging.info(f"Wizard: Successfully deleted original file '{key}'.")
                
                success_count += 1
                logging.info(f"Wizard: Successfully processed '{key}'.")
                
            except ClientError as e:
                error_msg = f"Error processing {key}: {str(e)}"
                logging.error(f"Wizard: ClientError - {error_msg}")
                errors.append(error_msg)
                error_count += 1
            except Exception as e:
                error_msg = f"Unexpected error processing {key}: {str(e)}"
                logging.error(f"Wizard: {error_msg}")
                errors.append(error_msg)
                error_count += 1
        
        result_message = f"Successfully processed {success_count} files."
        if error_count > 0:
            result_message += f" {error_count} files had errors."
        
        logging.info(f"Wizard: Processing complete. {result_message}")
        
        return jsonify({
            "success": True,
            "message": result_message,
            "success_count": success_count,
            "error_count": error_count,
            "errors": errors
        })
        
    except Exception as e:
        logging.error(f"Wizard: Unexpected error during execution: {e}")
        return jsonify({
            "success": False,
            "message": f"Error: {str(e)}"
        })

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
        print(f"\nS3 Helper is running at: http://127.0.0.1:{port}")
        print("Note: In web mode, credentials are stored in browser session storage")
        print("Press Ctrl+C to stop the server\n")
        
        try:
            # Keep the main thread alive
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logging.info("Web server stopped by user")
            print("\nServer stopped. Goodbye!")
    else:
        # Run as desktop application with pywebview
        logging.info("Creating desktop window...")
        webview.create_window(
            'S3 Helper',
            f'http://127.0.0.1:{port}',
            width=1200,
            height=800,
            min_size=(800, 600),
            resizable=True
        )
        
        webview.start(debug=False)

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import boto3
import os
import signal
import threading
import time
import logging
from logging.handlers import RotatingFileHandler
from botocore.exceptions import ClientError, NoCredentialsError

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

app = Flask(__name__)
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
        bucket = data.get("bucket")
        current_prefix = data.get("prefix", "")

        logging.info(f"Browsing folders for bucket '{bucket}' with prefix '{current_prefix}'")

        if not access_key or not secret_key or not bucket:
            logging.warning("Missing required credentials for browsing folders.")
            return jsonify({"success": False, "message": "Missing required credentials"})

        # Create S3 session and client
        session = boto3.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key
        )
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
        bucket = data.get("bucket")

        logging.info(f"Testing connection to bucket '{bucket}'.")

        if not access_key or not secret_key or not bucket:
            logging.warning("Missing required credentials for connection test.")
            return jsonify({"success": False, "message": "Missing required credentials"})

        # Create S3 session and client
        session = boto3.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key
        )
        s3 = session.client("s3")

        # Test connection by trying to head the bucket
        s3.head_bucket(Bucket=bucket)
        logging.info(f"Successfully performed head_bucket on '{bucket}'.")

        # Also try to list objects to ensure we have proper permissions
        response = s3.list_objects_v2(Bucket=bucket, MaxKeys=1)
        logging.info(f"Successfully listed objects (MaxKeys=1) on '{bucket}'.")

        return jsonify({
            "success": True,
            "message": f"Connection successful! Bucket '{bucket}' is accessible."
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

@app.route("/", methods=["GET", "POST"])
def index():
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

if __name__ == "__main__":
    # Ensure templates and static directories exist
    if not os.path.exists('templates'):
        logging.warning("Templates directory not found!")
        print("WARNING: templates directory not found!")
    if not os.path.exists('static'):
        logging.warning("Static directory not found!")
        print("WARNING: static directory not found!")

    logging.info("Starting Flask app...")
    print("Starting Flask app...")
    logging.info(f"Templates folder: {app.template_folder}")
    print(f"Templates folder: {app.template_folder}")
    logging.info(f"Static folder: {app.static_folder}")
    print(f"Static folder: {app.static_folder}")
    logging.info("Press Ctrl+C to stop, or use the 'Terminate App' button from the result page")
    print("Press Ctrl+C to stop, or use the 'Terminate App' button from the result page")
    app.run(debug=True, host='0.0.0.0', port=5000)

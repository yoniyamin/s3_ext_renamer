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
            'filename_placeholder': '${filename}'  # Clean placeholder for JavaScript
        }
        
        logging.info(f"Rendering upload form template with key_prefix: {key_prefix}")
        
        # Render the template instead of using embedded HTML string
        return render_template('upload_form.html', **template_params)
        
    except Exception as e:
        logging.error(f"Error rendering upload form template: {e}")
        raise

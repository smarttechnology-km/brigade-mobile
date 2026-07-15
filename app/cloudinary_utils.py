"""
Cloudinary integration — Option 2 (prod only).

Set USE_CLOUDINARY=true on Render to activate.
In local dev, all functions fall back to local disk behavior.
"""
import os


def is_cloudinary_enabled():
    return os.environ.get('USE_CLOUDINARY', '').lower() in ('true', '1', 'yes')


def _configure():
    import cloudinary
    cloudinary.config(
        cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
        api_key=os.environ.get('CLOUDINARY_API_KEY'),
        api_secret=os.environ.get('CLOUDINARY_API_SECRET'),
        secure=True,
    )


def upload_file(file_obj, folder):
    """
    Upload file_obj to Cloudinary under brigade/<folder>/.
    Returns the secure URL string.
    Raises on failure.
    """
    import cloudinary.uploader
    _configure()
    result = cloudinary.uploader.upload(
        file_obj,
        folder=f'brigade/{folder}',
        resource_type='auto',
    )
    return result['secure_url']


def delete_file(stored_value, local_folder=None):
    """
    Delete a file.
    - If stored_value is a Cloudinary URL: delete from Cloudinary.
    - Otherwise: delete local file at UPLOAD_FOLDER/local_folder/stored_value.
    """
    if not stored_value:
        return
    if stored_value.startswith('https://res.cloudinary.com'):
        try:
            import cloudinary.uploader
            _configure()
            # Extract public_id: everything after /upload/v<digits>/ without extension
            parts = stored_value.split('/')
            upload_idx = parts.index('upload')
            # skip version segment (v<digits>)
            after_version = parts[upload_idx + 2:]
            public_id = '/'.join(after_version).rsplit('.', 1)[0]
            cloudinary.uploader.destroy(public_id, resource_type='image')
        except Exception as e:
            print(f'[Cloudinary] delete error: {e}')
    elif local_folder:
        from flask import current_app
        path = os.path.join(current_app.config['UPLOAD_FOLDER'], local_folder, stored_value)
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError as e:
                print(f'[local] delete error: {e}')


def file_url(stored_value, local_folder):
    """
    Return the public URL for a stored file value.
    - Cloudinary URL → returned as-is.
    - Local filename   → /uploads/<local_folder>/<filename>
    """
    if not stored_value:
        return None
    if stored_value.startswith('https://'):
        return stored_value
    return f'/uploads/{local_folder}/{stored_value}'

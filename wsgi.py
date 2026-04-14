#!/usr/bin/env python
"""
WSGI entry point for Gunicorn
This file allows Gunicorn to properly import and run the Flask app
"""
import os
from run import app

# Debug: Print paths
print(f"App root dir: {os.path.dirname(os.path.abspath(__file__))}")
print(f"Template folder: {app.template_folder}")
print(f"Template folder exists: {os.path.exists(app.template_folder) if app.template_folder else 'N/A'}")
if app.template_folder:
    try:
        print(f"Templates: {os.listdir(app.template_folder)}")
    except Exception as e:
        print(f"Error listing templates: {e}")

if __name__ == "__main__":
    app.run()

#!/usr/bin/env python
"""
WSGI entry point for Gunicorn
This file allows Gunicorn to properly import and run the Flask app
"""
from run import app

if __name__ == "__main__":
    app.run()

#!/bin/bash

# Install system dependencies for Python packages
apt-get update
apt-get install -y python3-dev libjpeg-dev zlib1g-dev

# Install Python dependencies
pip install --upgrade pip setuptools wheel
pip install -r requirements-prod.txt

# Create directories if needed
mkdir -p /app/static /app/uploads

echo "Build completed successfully!"

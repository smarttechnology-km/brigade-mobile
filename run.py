#!/usr/bin/env python
"""
Application Flask pour le contrôle policier des véhicules aux Comores
"""
import os
import atexit
from app import create_app, db, scheduler
from app.models import Vehicle

app = create_app()

@app.shell_context_processor
def make_shell_context():
    """Contexte pour la shell Flask"""
    return {'db': db, 'Vehicle': Vehicle}

# Ensure scheduler shuts down properly on exit
@atexit.register
def shutdown_scheduler():
    if scheduler.running:
        scheduler.shutdown()

if __name__ == '__main__':
    try:
        app.run(debug=True, host='0.0.0.0', port=5001)
    finally:
        shutdown_scheduler()

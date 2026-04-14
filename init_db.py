#!/usr/bin/env python
"""
Script pour initialiser la base de données avec des données d'exemple
"""
import os
import sys
from app import create_app, db
from app.models import Vehicle, User, FineType
from datetime import datetime, timedelta
from app.models import User
from werkzeug.security import generate_password_hash

def init_db():
    """Initialiser la base de données avec des données d'exemple"""
    app = create_app()
    
    with app.app_context():
        # Supprimer les tables existantes (optionnel)
        db.drop_all()
        db.create_all()
        
        # Données d'exemple
        vehicles_data = []
        
        # Ajouter les véhicules à la base de données
        for vdata in vehicles_data:
            vehicle = Vehicle(**vdata)
            db.session.add(vehicle)
        
        db.session.commit()
        print(f"✓ {len(vehicles_data)} véhicules ont été ajoutés à la base de données")

        # Créer un utilisateur admin par défaut
        admin_username = 'admin'
        admin_password = 'admin123'  # Recommander de changer en production
        if not User.query.filter_by(username=admin_username).first():
            admin = User(username=admin_username, is_admin=True)
            admin.set_password(admin_password)
            db.session.add(admin)
            db.session.commit()
            print(f"✓ Utilisateur admin créé: {admin_username} / {admin_password}")

        # Seed default fine types if none exist
        default_types = [
            {'label': 'Non-port du casque', 'amount': 200.0},
            {'label': 'Excès de vitesse', 'amount': 500.0},
            {'label': 'Stationnement interdit', 'amount': 150.0},
        ]
        if not FineType.query.first():
            for t in default_types:
                ft = FineType(label=t['label'], amount=t['amount'])
                db.session.add(ft)
            db.session.commit()
            print(f"✓ {len(default_types)} types d'amandes ajoutés")
        print("✓ Base de données initialisée avec succès!")

if __name__ == '__main__':
    init_db()

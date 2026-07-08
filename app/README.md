# Police Comores - Système de Contrôle des Véhicules

Application web Flask pour la gestion centralisée du contrôle policier des véhicules aux Comores.

## Fonctionnalités

- 📊 **Dashboard** avec statistiques en temps réel
- 📋 **Gestion des véhicules** - Enregistrement et suivi
- 📈 **Graphiques** - Visualisation des données par type et statut
- 🔍 **Recherche et filtrage** - Accès rapide aux informations
- 📱 **Interface responsive** - Compatible mobile et desktop

## Structure du Projet

```
Police/
├── app/
│   ├── templates/           # Fichiers HTML (Jinja2)
│   │   ├── base.html       # Template de base
│   │   ├── index.html      # Page d'accueil
│   │   └── dashboard.html  # Page du dashboard
│   ├── static/
│   │   ├── css/
│   │   │   └── style.css   # Styles personnalisés
│   │   └── js/
│   │       └── dashboard.js # JavaScript pour le dashboard
│   ├── __init__.py         # Configuration Flask
│   ├── models.py           # Modèles de données
│   └── routes.py           # Routes de l'application
├── run.py                  # Point d'entrée
├── init_db.py             # Script d'initialisation de la BD
├── requirements.txt       # Dépendances Python
└── README.md             # Cette documentation
```

## Installation

### Prérequis
- Python 3.7+
- pip (gestionnaire de paquets Python)

### Étapes

1. **Cloner le repository** (si depuis Git)
   ```bash
   cd /Users/mohamedabdallah/Desktop/Police
   ```

2. **Créer un environnement virtuel**
   ```bash
   python -m venv venv
   source venv/bin/activate  # Sur macOS/Linux
   # ou
   venv\Scripts\activate  # Sur Windows
   ```

3. **Installer les dépendances**
   ```bash
   pip install -r requirements.txt
   ```

4. **Initialiser la base de données**
   ```bash
   python init_db.py
   ```

5. **Lancer l'application**
   ```bash
   python run.py
   ```

6. **Accéder à l'application**
   - Ouvrir le navigateur et aller à `http://localhost:5000`

## Utilisation

### Page d'accueil
- Présentation générale du système
- Liens rapides vers le dashboard et autres sections

### Dashboard
- Vue d'ensemble des statistiques des véhicules
- Total des véhicules enregistrés
- Répartition par type (voiture, moto, camion, etc.)
- Répartition par statut (actif, inactif, suspendu)
- Liste des véhicules récemment enregistrés
- Graphiques interactifs avec Chart.js

## Technologies Utilisées

- **Backend**: Flask 2.3.2
- **Database**: SQLite avec SQLAlchemy
- **Frontend**: Bootstrap 5.3.0
- **Graphiques**: Chart.js 4.3.0
- **Icons**: Font Awesome 6.4.0

## API Endpoints

### Véhicules
- `GET /api/vehicles/stats` - Obtenir les statistiques des véhicules
- `GET /api/vehicles/list` - Obtenir la liste complète des véhicules
- `POST /api/vehicles` - Ajouter un nouveau véhicule (à implémenter)

### Pages
- `GET /` - Page d'accueil
- `GET /dashboard` - Dashboard principal

## Configuration

### Variables d'environnement

Créer un fichier `.env` à la racine du projet:
```
FLASK_ENV=development
FLASK_DEBUG=True
SECRET_KEY=votre-clé-secrète
```

### Base de données

La base de données SQLite est créée automatiquement lors du premier démarrage.
Elle est stockée dans `/tmp/police_db.db` (configurable dans `app/__init__.py`)

## Développement

### Ajouter un nouveau modèle

1. Créer la classe dans `app/models.py`
2. Exécuter `python init_db.py` pour mettre à jour la BD

### Ajouter une nouvelle route

1. Ajouter la route dans `app/routes.py`
2. Créer le template correspondant dans `app/templates/`

### Ajouter des styles

- Modifier `app/static/css/style.css` pour les styles globaux
- Ajouter des styles spécifiques dans les templates

## Dépannage

### La base de données n'existe pas
```bash
python init_db.py
```

### Erreur "Port 5000 déjà utilisé"
Changer le port dans `run.py`:
```python
app.run(debug=True, host='0.0.0.0', port=5001)
```

### Erreur d'import de modules
```bash
pip install -r requirements.txt
```

## Améliorations Futures

- [ ] Authentification et autorisation
- [ ] Gestion complète CRUD des véhicules
- [ ] Historique des inspections
- [ ] Rapport PDF
- [ ] Système de notifications
- [ ] Export des données
- [ ] Tests unitaires
- [ ] CI/CD Pipeline

## Auteur

Contrôle Policier des Véhicules - Comores

## Licence

À définir

## Support

Pour plus d'informations ou pour signaler des bugs, veuillez contacter l'équipe IT.


**Dernière mise à jour**: Décembre 2025

## Applications mobiles

Le projet inclut deux applications mobiles React Native : une pour les agents (application police) et une pour les citoyens.

- **Police (application agents)**: dossier `mobile/` — application utilisée par les agents pour scanner, saisir et gérer les amendes.
- **Citizen (application citoyen)**: dossier `mobile-citizen/` — application destinée aux citoyens pour payer et consulter les reçus.

Prérequis généraux : Node.js, npm/yarn, React Native CLI, Android SDK (pour Android), CocoaPods (pour iOS).

Instructions rapides pour le développement local :

Police app:

```bash
cd mobile
npm install
# iOS
npx pod-install ios && npx react-native run-ios
# Android
npx react-native run-android
```

Citizen app:

```bash
cd mobile-citizen
npm install
# iOS
npx pod-install ios && npx react-native run-ios
# Android
npx react-native run-android
```

Consultez les fichiers `package.json` dans chaque dossier pour des scripts et dépendances spécifiques.


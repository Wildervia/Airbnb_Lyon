LYON RENTAL INTELLIGENCE — ASSISTANT IA FIABILISÉ

1. Décompressez le dossier lyon_dashboard.
2. Ouvrez .streamlit/secrets.toml et remplacez uniquement REMPLACE_ICI_PAR_TA_CLE_API par une NOUVELLE clé Google AI Studio.
3. Si besoin, changez GEMINI_MODEL par un modèle accessible à votre compte. L'application tente aussi d'identifier les modèles accessibles.
4. Installez les dépendances :
   python -m pip install -r requirements.txt
5. Lancez :
   python -m streamlit run app.py
6. Ouvrez https://airbnb-lyon.streamlit.app/ .

Améliorations : calculs locaux toujours affichés, tableau croisé avis × année × type, barres empilées, nouvelles tentatives en cas d'erreur temporaire, recherche d'un modèle de secours disponible.

La clé API n'est pas incluse. Ne publiez pas secrets.toml.

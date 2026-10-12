"""
Configuration du service. Les vraies valeurs viennent de variables
d'environnement (jamais écrites en dur ici) — voir .env.example.
"""

import os

from dotenv import load_dotenv

# ⚠️ Sans cette ligne, le fichier .env n'est JAMAIS lu automatiquement —
# c'est un simple fichier texte tant que rien ne le charge explicitement.
# C'était la cause de "LLM_API_KEY n'est pas configurée" malgré un .env rempli.
load_dotenv()

# L'adresse de VOTRE Django (celle que le frontend Angular utilise déjà)
DJANGO_BASE_URL = os.environ.get("DJANGO_BASE_URL", "http://localhost:8001")

# ⚠️ Fournisseur d'IA : n'importe quel service compatible avec le format
# "chat completions" d'OpenAI convient (Groq, OpenRouter, Cerebras...).
# Par défaut : OpenRouter, car Groq s'est révélé bloqué depuis certains
# réseaux. Pour changer de fournisseur, modifiez UNIQUEMENT ces 3 lignes
# dans votre .env — jamais besoin de toucher au code. Voir .env.example.
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://openrouter.ai/api/v1/chat/completions")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "openrouter/free")

# D'où le frontend Angular a le droit d'appeler ce service
ORIGINES_AUTORISEES = os.environ.get("CHATBOT_CORS_ORIGINS", "http://localhost:4200").split(",")
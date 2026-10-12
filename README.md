# SamaPass – Chatbot IA (FastAPI)

Assistant conversationnel de la plateforme SamaPass. Il répond en s'appuyant sur les **vraies données** de l'utilisateur connecté, lues via l'API Django avec son propre jeton.

## Fonctionnement

1. `intents.py` détecte ce que demande l'utilisateur (billets, favoris, ventes, solde, événements, etc.) et calcule les totaux en Python.
2. `django_client.py` interroge l'API Django avec le jeton de l'utilisateur : le chatbot ne voit que ce que l'utilisateur a le droit de voir.
3. `llm.py` demande à un modèle de langage (API compatible OpenAI, configurée par `.env`) de reformuler la réponse en deux phrases.
4. `navigation.py` ajoute des liens réels vers les pages du site selon le rôle (utilisateur, organisateur, administrateur).

## Routes

- `GET /sante` : vérification de l'état du service
- `POST /chat` : envoi d'un message et de l'historique, réponse + liens

## Installation

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # renseigner les valeurs
uvicorn main:app --reload --port 8001
```

## Docker

```bash
docker build -t samapass-chatbot -f dockerfile .
```

## Dépôts liés

- Frontend : `SamaPass-Frontend`
- Backend : `Kcrowd-backend`

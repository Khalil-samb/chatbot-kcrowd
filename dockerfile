
FROM python:3.12-slim

WORKDIR /app

# Copier UNIQUEMENT requirements.txt d'abord : Docker met cette étape en
# cache tant que ce fichier ne change pas, donc l'installation ne se
# relance pas à chaque modification de votre code Python.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copier le reste du service (main.py, config.py, navigation.py, etc.)
COPY . .

EXPOSE 8002

#  Pas de --reload ici (contrairement à votre usage en développement) :
# --reload est fait pour détecter vos modifications de code en direct sur
# votre machine, ce qui n'a aucun sens dans un conteneur figé. Sans lui,
# le service démarre aussi plus vite et consomme moins de ressources.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
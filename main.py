from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import django_client as dj
import llm
from config import ORIGINES_AUTORISEES
from intents import construire_contexte_donnees
from navigation import trouver_liens
from schemas import LienReponse, ReponseChat, RequeteChat


app = FastAPI(title="SamaPass Chatbot")


app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGINES_AUTORISEES,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


def extraire_jeton(authorization: str | None) -> str:
    """
    Récupère le JWT envoyé par Angular.

    Exemple :
    Authorization: Bearer eyJ...
    """

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Jeton d'authentification manquant.",
        )

    return authorization.removeprefix("Bearer ").strip()


@app.get("/sante")
async def sante():
    """
    Vérifie que le service FastAPI fonctionne.
    """
    return {
        "statut": "ok",
        "service": "SamaPass Chatbot",
    }


@app.post("/chat", response_model=ReponseChat)
async def chat(
    requete: RequeteChat,
    authorization: str | None = Header(default=None),
):
    """
    Endpoint principal du chatbot.
    """

    # 1. Récupérer le JWT envoyé par Angular
    jeton = extraire_jeton(authorization)

    # 2. Vérifier l'utilisateur auprès de Django
    try:
        identite = await dj.qui_est_ce(jeton)

    except dj.ErreurDjango as erreur:
        raise HTTPException(
            status_code=401,
            detail=str(erreur),
        ) from erreur

    # 3. Récupérer les informations de l'utilisateur
    role = identite.get("role", "user")
    prenom = identite.get("firstName", "")

    # 4. Récupérer les données réelles nécessaires
    #    depuis Django
    donnees = await construire_contexte_donnees(
        requete.message,
        role,
        jeton,
    )

    # 5. Déterminer les éventuels liens de navigation
    liens = trouver_liens(
        requete.message,
        role,
    )

    # 6. Transformer l'historique reçu par FastAPI
    #    dans le format attendu par le LLM
    historique_brut = [
        {
            "role": message.role,
            "content": message.content,
        }
        for message in requete.historique
    ]

    # 7. Appeler le modèle IA
    try:
        texte_reponse = await llm.generer_reponse(
            role=role,
            prenom=prenom,
            message=requete.message,
            donnees=donnees,
            historique=historique_brut,
        )

    except llm.ErreurLLM as erreur:
        raise HTTPException(
            status_code=502,
            detail=str(erreur),
        ) from erreur

    # 8. Retourner la réponse au frontend
    return ReponseChat(
        reponse=texte_reponse,
        liens=[
            LienReponse(
                label=l.label,
                path=l.path,
            )
            for l in liens
        ],
    )
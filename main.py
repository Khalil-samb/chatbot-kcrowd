import re

from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

import django_client as dj
import evenements
import gemini
import llm
from config import ORIGINES_AUTORISEES
from intents import construire_contexte_donnees
from navigation import trouver_liens
from schemas import LienReponse, ReponseChat, ReponseVocale, RequeteChat, RequeteVocale, RequeteVoix

TAILLE_MAX_AUDIO_B64 = 6_000_000  # environ 4 Mo d'audio
CHEMIN_EVENEMENT = "/evenements/{id}"  # page d'un événement dans l'application
EMOJIS = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]")

app = FastAPI(title="Kcrowd Chatbot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGINES_AUTORISEES,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


def extraire_jeton(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Jeton d'authentification manquant.")
    return authorization.removeprefix("Bearer ").strip()


async def identifier(authorization: str | None):
    jeton = extraire_jeton(authorization)
    try:
        identite = await dj.qui_est_ce(jeton)
    except dj.ErreurDjango as erreur:
        raise HTTPException(status_code=401, detail=str(erreur)) from erreur
    return jeton, identite


async def repondre(message: str, historique, jeton: str, identite: dict):
    """Le même traitement pour un message écrit et pour un message vocal déjà transcrit."""
    role = identite.get("role", "user")
    prenom = identite.get("firstName", "")

    donnees = await construire_contexte_donnees(message, role, jeton)
    liste_evenements = await evenements.lignes_evenements()
    liens = trouver_liens(message, role)
    historique_brut = [{"role": m.role, "content": m.content} for m in historique]

    try:
        texte = await llm.generer_reponse(
            role=role,
            prenom=prenom,
            message=message,
            donnees=donnees,
            historique=historique_brut,
            evenements=liste_evenements,
        )
    except llm.ErreurLLM as erreur:
        raise HTTPException(status_code=502, detail=str(erreur)) from erreur

    liens_reponse = [
        LienReponse(label=item["titre"], path=CHEMIN_EVENEMENT.format(id=item["id"]))
        for item in evenements.evenements_cites(texte)
    ]
    if liens_reponse and not any(l.path == "/evenements" for l in liens):
        liens_reponse.append(LienReponse(label="Voir tous les événements", path="/evenements"))
    deja = {l.path for l in liens_reponse}
    liens_reponse += [LienReponse(label=l.label, path=l.path) for l in liens if l.path not in deja]
    return texte, liens_reponse[:5]


@app.get("/sante")
async def sante():
    return {"statut": "ok", "service": "Kcrowd Chatbot"}


@app.get("/evenements-apercu")
async def evenements_apercu():
    """Ce que l'IA voit des événements (données publiques) : sert à vérifier la connexion avec Django."""
    lignes = await evenements.lignes_evenements()
    return {"lignes": lignes, "erreur": evenements._cache["erreur"], "champs_du_premier": evenements._cache["cles"]}


@app.post("/chat", response_model=ReponseChat)
async def chat(requete: RequeteChat, authorization: str | None = Header(default=None)):
    jeton, identite = await identifier(authorization)
    texte, liens = await repondre(requete.message, requete.historique, jeton, identite)
    return ReponseChat(reponse=texte, liens=liens)


@app.post("/chat-vocal", response_model=ReponseVocale)
async def chat_vocal(requete: RequeteVocale, authorization: str | None = Header(default=None)):
    jeton, identite = await identifier(authorization)
    if len(requete.audio_base64) > TAILLE_MAX_AUDIO_B64:
        raise HTTPException(status_code=413, detail="Message vocal trop long.")
    try:
        transcription, langue = await gemini.transcrire(requete.audio_base64, requete.mime_type)
    except gemini.ErreurGemini as erreur:
        raise HTTPException(status_code=502, detail=str(erreur)) from erreur
    if not transcription:
        raise HTTPException(status_code=422, detail="Je n'ai pas compris l'audio. Réessayez en parlant plus près du micro.")
    texte, liens = await repondre(transcription, requete.historique, jeton, identite)
    return ReponseVocale(transcription=transcription, langue=langue, reponse=texte, liens=liens)


@app.post("/voix")
async def voix(requete: RequeteVoix, authorization: str | None = Header(default=None)):
    await identifier(authorization)
    texte = EMOJIS.sub("", requete.texte).strip()[:700]
    if not texte:
        raise HTTPException(status_code=422, detail="Texte vide.")
    try:
        wav = await gemini.synthetiser(texte)
    except gemini.ErreurGemini as erreur:
        raise HTTPException(status_code=502, detail=str(erreur)) from erreur
    return Response(content=wav, media_type="audio/wav")

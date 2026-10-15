"""
Voix avec Gemini : transcription d'un message vocal et lecture d'une réponse à voix haute.
Réglages dans .env : GEMINI_API_KEY, GEMINI_MODEL_AUDIO, GEMINI_MODEL_TTS, GEMINI_VOIX.
"""
import base64
import io
import json
import os
import re
import wave

import httpx

from config import LLM_API_KEY

CLE = os.environ.get("GEMINI_API_KEY", "").strip() or LLM_API_KEY
MODELE_AUDIO = os.environ.get("GEMINI_MODEL_AUDIO") or os.environ.get("LLM_MODEL") or "gemini-flash-lite-latest"
MODELE_TTS = os.environ.get("GEMINI_MODEL_TTS", "gemini-3.8-flash-lite-tts")
VOIX = os.environ.get("GEMINI_VOIX", "Kore")
URL = "https://generativelanguage.googleapis.com/v1beta/models/{modele}:generateContent"
DELAI = httpx.Timeout(45.0)

CONSIGNE_TRANSCRIPTION = (
    "Transcris fidèlement ce message vocal, dans sa langue d'origine (français, wolof ou anglais). "
    "Écris le wolof en alphabet latin. Ne réponds pas à la question, ne traduis pas, n'ajoute rien. "
    "Renvoie la transcription et la langue détectée : fr, wo ou en. "
    "Si l'audio est inaudible ou vide, renvoie une transcription vide."
)


class ErreurGemini(Exception):
    pass


async def _appeler(modele: str, corps: dict) -> dict:
    if not CLE:
        raise ErreurGemini("GEMINI_API_KEY n'est pas configurée (voir .env).")
    try:
        async with httpx.AsyncClient(timeout=DELAI) as client:
            reponse = await client.post(URL.format(modele=modele), json=corps, headers={"x-goog-api-key": CLE})
    except httpx.RequestError as erreur:
        raise ErreurGemini(f"Gemini injoignable : {erreur!r}") from erreur
    if reponse.status_code != 200:
        raise ErreurGemini(f"Gemini a répondu {reponse.status_code} ({modele}) : {reponse.text[:300]}")
    try:
        return reponse.json()
    except ValueError as erreur:
        raise ErreurGemini("Réponse Gemini illisible.") from erreur


async def transcrire(audio_base64: str, mime_type: str) -> tuple:
    corps = {
        "contents": [{"parts": [{"text": CONSIGNE_TRANSCRIPTION}, {"inline_data": {"mime_type": mime_type, "data": audio_base64}}]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {"transcription": {"type": "STRING"}, "langue": {"type": "STRING"}},
                "required": ["transcription", "langue"],
            },
        },
    }
    donnees = await _appeler(MODELE_AUDIO, corps)
    try:
        parties = donnees["candidates"][0]["content"]["parts"]
        resultat = json.loads("".join(p.get("text", "") for p in parties))
        return str(resultat.get("transcription", "")).strip(), str(resultat.get("langue", "fr")).strip().lower()
    except (KeyError, IndexError, TypeError, ValueError) as erreur:
        raise ErreurGemini(f"Transcription illisible : {str(donnees)[:200]}") from erreur


async def synthetiser(texte: str) -> bytes:
    corps = {
        "contents": [{"parts": [{"text": texte}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": VOIX}}},
        },
    }
    donnees = await _appeler(MODELE_TTS, corps)
    try:
        blob = None
        for partie in donnees["candidates"][0]["content"]["parts"]:
            blob = partie.get("inlineData") or partie.get("inline_data")
            if blob:
                break
        octets = base64.b64decode(blob["data"])
        mime = blob.get("mimeType") or blob.get("mime_type") or ""
    except (KeyError, IndexError, TypeError, ValueError) as erreur:
        raise ErreurGemini(f"Audio absent de la réponse : {str(donnees)[:200]}") from erreur

    if octets[:4] == b"RIFF":
        return octets
    taux = re.search(r"rate=(\d+)", mime)
    tampon = io.BytesIO()
    with wave.open(tampon, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(taux.group(1)) if taux else 24000)
        w.writeframes(octets)
    return tampon.getvalue()

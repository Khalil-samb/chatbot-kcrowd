"""
Événements réels de Kcrowd pour l'IA : lus sur l'API publique de Django
(jamais inventés), gardés 60 s en mémoire pour ne pas la solliciter à chaque message.
"""
import logging
import time
import unicodedata

import httpx

from config import DJANGO_BASE_URL

logger = logging.getLogger("chatbot.evenements")

DUREE_CACHE_S = 60
MAX_EVENEMENTS = 10
_cache: dict = {"t": 0.0, "lignes": [], "items": [], "erreur": None, "cles": []}


JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre"]


def _date_lisible(brut: str) -> str:
    """'2026-10-30T22:00:00Z' -> 'vendredi 30 octobre 2026 à 22h00' (heure telle qu'enregistrée)."""
    from datetime import datetime
    try:
        d = datetime.fromisoformat(brut.replace("Z", "+00:00"))
    except ValueError:
        return brut[:16].replace("T", " à ")
    return f"{JOURS[d.weekday()]} {d.day} {MOIS[d.month - 1]} {d.year} à {d.hour}h{d.minute:02d}"


def _texte(valeur) -> str:
    if valeur is None:
        return ""
    if isinstance(valeur, dict):
        return str(valeur.get("name") or valeur.get("title") or valeur.get("label") or "").strip()
    return str(valeur).strip()


def _premier(evenement: dict, *cles) -> str:
    for cle in cles:
        texte = _texte(evenement.get(cle))
        if texte:
            return texte
    return ""


def _prix_min(evenement: dict):
    for cle in ("prixMin", "minPrice", "priceFrom", "startingPrice", "lowestPrice"):
        try:
            return float(evenement.get(cle))
        except (TypeError, ValueError):
            pass
    prix = []
    for t in evenement.get("ticketTypes") or []:
        if isinstance(t, dict):
            try:
                prix.append(float(t.get("price")))
            except (TypeError, ValueError):
                pass
    return min(prix) if prix else None


def _etat(evenement: dict):
    statut = _texte(evenement.get("status")).lower()
    vente = _texte(evenement.get("salesState")).lower()
    if statut in ("finished", "cancelled", "draft") or vente in ("ended", "unavailable"):
        return None
    if statut == "sold_out" or vente == "sold_out":
        return "complet"
    if vente == "closed":
        return "ventes closes"
    if vente == "not_open":
        return "ventes pas encore ouvertes"
    return "billets disponibles"


def _ligne(evenement: dict):
    etat = _etat(evenement)
    titre = _premier(evenement, "title", "name")
    if etat is None or not titre:
        return None
    morceaux = [f"« {titre} »"]
    if evenement.get("isSponsored"):
        morceaux.append("à la une")
    date = _premier(evenement, "startDate", "date", "startAt")
    if date:
        morceaux.append("date : " + _date_lisible(date))
    lieu = _premier(evenement, "venue", "venueName", "locationName", "location", "address")
    ville = _premier(evenement, "city", "cityName")
    endroit = ", ".join(x for x in (lieu, ville) if x)
    if endroit:
        morceaux.append("lieu : " + endroit)
    categorie = _premier(evenement, "category", "categoryName")
    if categorie:
        morceaux.append("catégorie : " + categorie)
    prix = _prix_min(evenement)
    if prix is not None:
        morceaux.append(f"à partir de {prix:,.0f} FCFA".replace(",", " "))
    morceaux.append("état : " + etat)
    return " | ".join(morceaux)


async def lignes_evenements() -> list:
    if _cache["t"] and time.time() - _cache["t"] < DUREE_CACHE_S:
        return _cache["lignes"]
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(6.0)) as client:
            reponse = await client.get(f"{DJANGO_BASE_URL}/api/events/")
        reponse.raise_for_status()
        donnees = reponse.json()
        liste = donnees.get("results", []) if isinstance(donnees, dict) else donnees
        lignes, items = [], []
        for e in liste:
            if not isinstance(e, dict):
                continue
            ligne = _ligne(e)
            if ligne:
                lignes.append(ligne)
                items.append({"id": e.get("id"), "titre": _premier(e, "title", "name")})
            if len(lignes) >= MAX_EVENEMENTS:
                break
        cles = sorted(liste[0].keys()) if liste and isinstance(liste[0], dict) else []
        _cache.update(t=time.time(), lignes=lignes, items=items, erreur=None, cles=cles)
    except (httpx.HTTPError, ValueError) as erreur:
        logger.warning("Impossible de charger les événements : %s", erreur)
        _cache.update(t=time.time() - DUREE_CACHE_S + 10, erreur=str(erreur))
    return _cache["lignes"]


def _normaliser(texte: str) -> str:
    sans_accents = unicodedata.normalize("NFKD", texte or "")
    return "".join(c for c in sans_accents if not unicodedata.combining(c)).lower()


def evenements_cites(texte: str, maximum: int = 3) -> list:
    """Les événements réels dont le titre apparaît dans la réponse de l'IA, dans l'ordre où elle les cite."""
    t = _normaliser(texte)
    trouves = []
    for item in _cache.get("items", []):
        if item.get("id") and item.get("titre"):
            position = t.find(_normaliser(item["titre"]))
            if position >= 0:
                trouves.append((position, item))
    trouves.sort(key=lambda paire: paire[0])
    return [item for _position, item in trouves[:maximum]]

"""
Appelle VOTRE Django existant, avec le même jeton (Bearer) que la personne
utilise déjà dans l'application. FastAPI ne se connecte jamais directement à
la base de données : il passe toujours par l'API Django, qui applique déjà
les bonnes permissions (un utilisateur ne peut réclamer que SES données).

Les chemins ci-dessous sont reconstitués à partir de la session de
construction du backend. Si un appel échoue (404), vérifiez le chemin exact
dans votre urls.py et corrigez-le ici — un seul endroit à changer.
"""

import httpx

from config import DJANGO_BASE_URL

TIMEOUT = httpx.Timeout(6.0)


class ErreurDjango(Exception):
    """Le jeton est invalide/expiré, ou Django est injoignable."""


async def _get(chemin: str, jeton: str) -> dict | list:
    url = f"{DJANGO_BASE_URL}{chemin}"
    en_tetes = {"Authorization": f"Bearer {jeton}"}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            reponse = await client.get(url, headers=en_tetes)
    except httpx.RequestError as erreur:
        raise ErreurDjango(f"Django injoignable sur {url} : {erreur}") from erreur

    if reponse.status_code == 401:
        raise ErreurDjango("Jeton invalide ou expiré.")
    if reponse.status_code >= 400:
        raise ErreurDjango(f"Django a répondu {reponse.status_code} sur {chemin}.")
    return reponse.json()


async def qui_est_ce(jeton: str) -> dict:
    """
    GET /api/auth/whoami/ — LE nouvel endpoint à ajouter côté Django (voir
    django_whoami_endpoint.py). Fonctionne pour n'importe quel rôle connecté.
    Renvoie : {"id", "role", "firstName", "lastName"}
    """
    return await _get("/api/auth/whoami/", jeton)


# ── Utilisateur ──

async def mes_billets(jeton: str) -> list:
    return await _get("/api/tickets/me/", jeton)


async def mes_favoris(jeton: str) -> list:
    return await _get("/api/engagement/favorites/", jeton)


# ── Organisateur ──

async def mes_ventes_organisateur(jeton: str) -> list:
    """Transactions de tous les événements de l'organisateur connecté."""
    return await _get("/api/transactions/organizers/me/", jeton)


async def mon_solde_organisateur(jeton: str) -> dict:
    return await _get("/api/payouts/solde/", jeton)


async def mes_evenements_organisateur(jeton: str) -> list:
    return await _get("/api/events/organizers/me/events/", jeton)


# ── Administrateur ──

async def toutes_les_transactions(jeton: str) -> list:
    return await _get("/api/transactions/admin/all/", jeton)


async def tous_les_utilisateurs(jeton: str) -> list:
    return await _get("/api/auth/admin/users/", jeton)


async def tous_les_organisateurs(jeton: str) -> list:
    return await _get("/api/auth/admin/organizers/", jeton)
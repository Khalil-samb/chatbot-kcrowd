"""
Appelle un fournisseur d'IA compatible avec le format "chat completions"
d'OpenAI. Le fournisseur exact (Groq, OpenRouter, Cerebras...) se règle
UNIQUEMENT dans .env (LLM_BASE_URL, LLM_API_KEY, LLM_MODEL) — ce fichier ne
connaît aucun nom de fournisseur en dur, pour pouvoir changer sans coder.
"""

import asyncio
import re

import httpx

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL

NOMS_ROLE = {"user": "un utilisateur (acheteur de billets)", "organizer": "un organisateur d'événements", "admin": "un administrateur de la plateforme"}


class ErreurLLM(Exception):
    pass


_FIN_DE_PHRASE = re.compile(r"(?<=[.!?])\s+")


def limiter_a_deux_phrases(texte: str) -> str:
    """
    Certains modèles gratuits ignorent la consigne de brièveté et répondent
    par un mode d'emploi complet. On garde au plus les 2 premières phrases —
    jamais une coupure en plein mot, toujours sur une vraie fin de phrase.
    Si le texte ne contient aucune ponctuation de fin, il est renvoyé tel quel
    plutôt que d'être charcuté au hasard.
    """
    phrases = _FIN_DE_PHRASE.split(texte.strip())
    if len(phrases) <= 2:
        return texte.strip()
    return " ".join(phrases[:2])


DESCRIPTION_SAMAPASS = {
    "user": (
        "SamaPass permet de : chercher des événements par ville, date ou catégorie sur la page "
        "'Rechercher' ; acheter des billets par Wave, Orange Money, Free Money ou carte ; "
        "recevoir son e-billet avec QR code ; mettre des événements en favoris ; consulter ses "
        "billets déjà achetés."
    ),
    "organizer": (
        "SamaPass permet à un organisateur de : créer et publier un événement avec ses catégories "
        "de billets ; suivre ses ventes et ses recettes ; scanner les billets à l'entrée ; lancer une "
        "campagne publicitaire ; demander le reversement de son solde vers Wave ou Orange Money."
    ),
    "admin": (
        "SamaPass permet à un administrateur de : superviser tous les utilisateurs et organisateurs "
        "(suspendre ou réactiver un compte) ; suivre la commission perçue par la plateforme (5 % sur "
        "chaque billet vendu) ; consulter les notifications et paramètres système."
    ),
}


def construire_prompt_systeme(role: str, prenom: str, donnees: list[str]) -> str:
    bloc_donnees = (
        "\n\nDONNÉES RÉELLES DE CETTE PERSONNE (à utiliser telles quelles, ne jamais inventer d'autre chiffre) :\n"
        + "\n".join(f"- {ligne}" for ligne in donnees)
        if donnees
        else "\n\nCette question ne demande pas de donnée personnelle chiffrée : réponds avec ce que tu sais du fonctionnement de SamaPass ci-dessus."
    )

    return (
        "Tu es l'assistant intégré à SamaPass, une billetterie en ligne au Sénégal. "
        f"Tu parles avec {NOMS_ROLE.get(role, 'une personne')}, prénom : {prenom}.\n\n"
        f"CE QUE SAMAPASS PERMET DE FAIRE : {DESCRIPTION_SAMAPASS.get(role, DESCRIPTION_SAMAPASS['user'])}\n\n"
        "RÈGLES STRICTES :\n"
        "- Réponds en 1 à 2 phrases COURTES maximum. Jamais une liste d'étapes, jamais un mode d'emploi complet.\n"
        "- Va droit au but : pas de formule de politesse en préambule (\"Bien sûr !\", \"Je suis ravi de...\").\n"
        "- Réponds UNIQUEMENT par une phrase normale en français, adressée à la personne. N'utilise JAMAIS\n"
        "  un format du genre \"Champ : valeur\" (par exemple \"Sécurité : sûr\", \"Statut : ok\") — ce n'est\n"
        "  ni une réponse ni ce qu'on te demande.\n"
        "- Pour une question générale sur SamaPass, réponds à partir de la description ci-dessus — ce n'est\n"
        "  PAS une donnée personnelle inconnue, c'est ce que l'application permet de faire.\n"
        "- N'invente JAMAIS un CHIFFRE, un NOM d'événement précis ou une donnée personnelle : ceux-là\n"
        "  viennent UNIQUEMENT de la section \"DONNÉES RÉELLES\" ci-dessous si elle est présente.\n"
        "- Si une donnée personnelle chiffrée est demandée mais absente ci-dessous, dis que tu ne l'as pas, sans deviner.\n"
        "- Ne mentionne jamais de lien ou de page toi-même : un autre système s'en charge séparément.\n"
        "- Réponds en français."
        + bloc_donnees
    )


async def generer_reponse(role: str, prenom: str, message: str, donnees: list[str], historique: list[dict]) -> str:
    if not LLM_API_KEY:
        raise ErreurLLM("LLM_API_KEY n'est pas configurée (voir .env).")

    messages = [{"role": "system", "content": construire_prompt_systeme(role, prenom, donnees)}]
    # Les 6 derniers échanges suffisent pour garder le contexte sans gonfler la requête
    messages.extend(historique[-6:])
    messages.append({"role": "user", "content": message})

    corps = {
        "model": LLM_MODEL,
        "messages": messages,
        "max_tokens": 150,  # marge suffisante pour 2 phrases complètes, sans risquer une coupure brutale
        "temperature": 0.3,  # peu de créativité : on veut de la précision, pas de l'invention
    }
    en_tetes = {"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"}

    derniere_erreur: Exception | None = None

    # Un fournisseur gratuit a parfois un raté ponctuel (surcharge, modèle
    # temporairement indisponible) — une seule nouvelle tentative, après une
    # courte pause, évite de faire échouer toute la conversation pour un
    # incident isolé de quelques secondes.
    for tentative in range(2):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
                reponse = await client.post(LLM_BASE_URL, json=corps, headers=en_tetes)
        except httpx.RequestError as erreur:
            derniere_erreur = ErreurLLM(f"Fournisseur IA injoignable ({LLM_BASE_URL}) : {erreur}")
        else:
            if reponse.status_code == 200:
                # Certains modèles du routeur gratuit renvoient parfois un
                # contenu vide (null) au lieu d'un texte — jamais vu jusqu'ici,
                # mais un HTTP 200 ne garantit pas un contenu exploitable.
                # On traite ça comme un raté temporaire : une nouvelle
                # tentative a de bonnes chances de tomber sur un autre modèle.
                contenu = reponse.json()["choices"][0]["message"]["content"]
                if contenu and contenu.strip():
                    return limiter_a_deux_phrases(contenu)
                derniere_erreur = ErreurLLM("Le fournisseur IA a renvoyé une réponse vide.")
            else:
                # 429 (trop de requêtes) et 5xx (souci temporaire du fournisseur) méritent
                # une seconde chance ; une erreur 4xx franche (mauvaise clé, etc.) non.
                if reponse.status_code not in (429, 500, 502, 503, 504):
                    raise ErreurLLM(f"Le fournisseur IA a répondu {reponse.status_code} : {reponse.text[:200]}")
                derniere_erreur = ErreurLLM(f"Le fournisseur IA a répondu {reponse.status_code} : {reponse.text[:200]}")

        if tentative == 0:
            await asyncio.sleep(1.5)

    raise derniere_erreur
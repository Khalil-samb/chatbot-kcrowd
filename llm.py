"""
Appelle un fournisseur d'IA compatible avec le format "chat completions" d'OpenAI.
Le fournisseur et le modèle se règlent UNIQUEMENT dans .env :
LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, et facultativement LLM_MODEL_SECOURS
(utilisé si le premier modèle échoue), LLM_MAX_TOKENS, LLM_TIMEOUT.
"""

import asyncio
import os
import re

import httpx

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL

LLM_MODEL_SECOURS = os.environ.get("LLM_MODEL_SECOURS", "").strip()
# Modèle plus précis, utilisé seulement pour les questions en wolof (facultatif).
LLM_MODEL_WOLOF = os.environ.get("LLM_MODEL_WOLOF", "").strip()
# Temps de réflexion du modèle (none, minimal, low, medium, high) : plus bas = plus rapide (facultatif).
EFFORT = os.environ.get("LLM_REASONING_EFFORT", "").strip()
MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "700"))
DELAI_S = float(os.environ.get("LLM_TIMEOUT", "40"))
NB_TENTATIVES = 3

NOMS_ROLE = {
    "user": "un utilisateur (acheteur de billets)",
    "organizer": "un organisateur d'événements",
    "admin": "un administrateur de la plateforme",
}


class ErreurLLM(Exception):
    pass


JOURS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
           "septembre", "octobre", "novembre", "décembre"]

# Mots qui n'existent pas en français : un seul suffit pour reconnaître du wolof.
MOTS_WOLOF = {"nanga", "def", "naka", "ndaje", "bileti", "njëg", "njeg", "yan", "ñaata", "jërëjëf", "jerejef",
              "ngi", "dafa", "bëgg", "begg", "damay", "mangi", "kañ", "fey", "dugg", "jàmm", "jamm", "waaw",
              "déedéet", "deedeet", "maa", "yaa", "nu", "sama", "dama", "mën", "mën", "ndax", "lan", "fan"}
MOTS_WOLOF_FORTS = {"nanga", "naka", "ndaje", "bileti", "njëg", "njeg", "yan", "ñaata", "jërëjëf", "jerejef", "ngi",
                    "dafa", "bëgg", "begg", "damay", "mangi", "kañ", "dugg", "jàmm", "waaw", "déedéet", "deedeet", "ndax"}
MOTS_ANGLAIS = {"what", "the", "can", "is", "are", "where", "when", "how", "do", "does", "events", "event", "weekend",
                "this", "tonight", "tickets", "ticket", "there", "any", "hello", "hi", "please", "my", "you", "for",
                "go", "show", "buy", "tomorrow", "today"}


def detecter_langue(message: str) -> str:
    """'wo', 'en' ou 'fr' — décidé par le serveur, pas laissé au bon vouloir du modèle."""
    mots = set(re.findall(r"[\w']+", message.lower()))
    if mots & MOTS_WOLOF_FORTS:
        return "wo"
    if len(mots & MOTS_ANGLAIS) >= 2:
        return "en"
    return "fr"


def date_du_jour() -> str:
    from datetime import datetime, timezone
    n = datetime.now(timezone.utc)  # Dakar = UTC+0, sans changement d'heure
    return f"{JOURS_FR[n.weekday()]} {n.day} {MOIS_FR[n.month - 1]} {n.year}"


# Réponses d'un modèle de modération (« User Safety: safe »…) ou de format machine : jamais une vraie réponse.
REPONSE_PARASITE = re.compile(r"^\s*(user|response|prompt)?\s*safety\s*[:=]|^\s*\{?\s*\"?(safety|category|label)\"?\s*[:=]", re.IGNORECASE)


CONNAISSANCES_COMMUNES = """\
Kcrowd est une billetterie en ligne pour le Sénégal : on y découvre des événements, on achète des billets avec un QR code, et les organisateurs vendent et contrôlent leurs billets.

POUR LES ACHETEURS :
- On peut parcourir les événements sans compte. Pour acheter, on s'identifie avec son numéro de téléphone et un code à 4 chiffres reçu par téléphone (valable 5 minutes).
- Sur la fiche d'un événement : choisir une catégorie de billet et une quantité, puis un moyen de paiement parmi ceux acceptés par l'organisateur (Wave, Orange Money, Free Money, carte bancaire), puis confirmer. Le prix affiché est exactement ce que l'acheteur paie.
- Le billet arrive tout de suite avec un QR code unique, dans « Mes billets ». Il peut être imprimé. Si le QR est abîmé, un code de secours de 8 caractères figure sur le billet : l'agent à l'entrée peut le saisir à la main.
- Un billet ne peut servir qu'une seule fois : s'il est scanné une deuxième fois, il est signalé comme déjà utilisé.
- L'organisateur fixe le nombre maximum de billets par achat.
- Le cœur sur un événement l'ajoute aux favoris. La cloche affiche les notifications.
- La rubrique Vidéos montre de courtes vidéos publiées par les organisateurs ; aimer une vidéo demande d'être connecté.
- Un événement peut être publié, complet, terminé ou annulé ; l'achat n'est possible que pour un événement publié dont les ventes sont ouvertes.

POUR LES ORGANISATEURS :
- Devenir organisateur : page « Devenir organisateur », formulaire (structure, contact, moyen de réception des fonds Wave ou Orange Money, mot de passe d'au moins 8 caractères). Ensuite la connexion se fait par email et mot de passe.
- Créer un événement en 4 étapes : 1) informations et lieu, 2) billetterie et tarifs (des modèles rapides Standard, VIP et Early bird préremplissent une catégorie), 3) contrôle et accès (portes d'entrée et agents de scan), 4) récapitulatif et publication. L'événement n'est visible du public qu'une fois publié ; en cas d'interruption il reste en brouillon dans « Mes événements ».
- Commission : Kcrowd prélève un pourcentage sur chaque billet vendu (5 % par défaut, fixé par l'administrateur). Il est déduit du reversement de l'organisateur ; l'acheteur ne paie jamais plus que le prix affiché. Le taux appliqué à une vente est celui en vigueur au moment de la vente.
- Reversements : le solde disponible correspond aux ventes nettes de commission moins ce qui a déjà été reversé. L'organisateur le demande depuis la page Reversements, vers Wave ou Orange Money.
- Scanner : page Scanner de contrôle, la caméra lit le QR code, on peut choisir la porte, et la saisie manuelle du code de secours existe. Résultats possibles : valide, déjà utilisé (doublon) ou invalide. La caméra demande une connexion sécurisée (HTTPS) ou localhost.
- Campagnes : l'offre « Boost » (15 000 FCFA) met un événement en avant sur la plateforme.
- Ventes & Billets : liste des billets vendus et suivi des recettes.

POUR LES ADMINISTRATEURS :
- Tableau de bord global, gestion des utilisateurs et des organisateurs (valider, suspendre, réactiver), notifications et paramètres de la plateforme.
- Le taux de commission se change dans les paramètres : plafond de 30 %, mot de passe de l'administrateur exigé, historique conservé.
"""


def construire_prompt_systeme(role: str, prenom: str, donnees: list[str], evenements: list[str] | None = None, langue: str = "fr") -> str:
    if donnees:
        bloc_donnees = (
            "\n\nDONNÉES RÉELLES DE CETTE PERSONNE (à utiliser telles quelles, ne jamais inventer d'autre chiffre) :\n"
            + "\n".join(f"- {ligne}" for ligne in donnees)
        )
    else:
        bloc_donnees = (
            "\n\nCette question ne demande pas de donnée personnelle chiffrée : réponds avec ce que tu sais "
            "du fonctionnement de Kcrowd ci-dessus."
        )

    directives_langue = {
        "en": "\n\nLANGUE DE CETTE RÉPONSE : ANGLAIS. La dernière question est en anglais : réponds ENTIÈREMENT en anglais (présentation des événements comprise). Garde seulement les noms propres, les dates et les prix en FCFA tels quels.",
        "wo": "\n\nLANGUE DE CETTE RÉPONSE : WOLOF. La dernière question est en wolof : réponds en wolof simple (alphabet latin) de bout en bout, avec de courtes phrases. Si la personne te salue, commence par « Maa ngi fi ». Garde en l'état les noms d'événements, les dates, les lieux et les prix en FCFA. Pour une précision que tu ne sais pas dire en wolof avec certitude, ajoute-la en français entre parenthèses plutôt que de l'inventer.",
    }
    bloc_contexte = (
        f"\n\nDATE D'AUJOURD'HUI (heure de Dakar) : {date_du_jour()}. "
        "Ne présente comme « ce soir », « demain », « ce week-end » ou « ce mois-ci » que les événements dont la date correspond vraiment ; "
        "sinon dis honnêtement qu'il n'y en a pas pour cette période et propose les plus proches."
        + directives_langue.get(langue, "")
    )

    if evenements:
        bloc_evenements = (
            "\n\nÉVÉNEMENTS DISPONIBLES SUR KCROWD (liste réelle : la seule source pour les noms, dates, lieux et prix) :\n"
            + "\n".join(f"- {ligne}" for ligne in evenements)
        )
    else:
        bloc_evenements = (
            "\n\nÉVÉNEMENTS DISPONIBLES SUR KCROWD : aucune liste n'a pu être chargée. "
            "Ne cite aucun événement précis ; invite la personne à ouvrir la page Événements."
        )

    return (
        "Tu es l'assistant de Kcrowd, la billetterie en ligne du Sénégal. "
        f"Tu parles avec {NOMS_ROLE.get(role, 'une personne')}, prénom : {prenom or 'inconnu'}.\n\n"
        "TA PERSONNALITÉ : chaleureux, naturel, patient et vraiment utile, comme un bon conseiller qui connaît "
        "parfaitement l'application. Tu es capable de discuter de tout avec simplicité.\n\n"
        "CE QUE TU SAIS SUR KCROWD :\n" + CONNAISSANCES_COMMUNES + "\n"
        "COMMENT RÉPONDRE :\n"
        "- Réponds TOUJOURS, et réponds complètement à la question posée. Pas de limite à deux phrases.\n"
        "- Adapte la longueur : une salutation ou une question simple appelle 1 à 3 phrases ; une question pratique "
        "(« comment faire ? ») appelle une explication claire, avec des étapes numérotées (1., 2., 3.) quand c'est utile, "
        "jusqu'à environ 200 mots.\n"
        "- Écris en texte simple : pas de markdown (pas de ** ni de #), phrases courtes, une étape par ligne.\n"
        "- Vouvoie par défaut ; si la personne te tutoie, tutoie-la.\n"
        "- LANGUES : tu comprends et tu parles français, anglais et wolof (écrit en alphabet latin). Réponds TOUJOURS dans la langue du dernier message de la personne ; si elle mélange wolof et français, fais de même. Si le message est en wolof, réponds en wolof simple et naturel. Mots utiles : bileti = billet ; ndaje = événement ; fey = payer ; njëg = prix ; dugg = entrer ; jërëjëf = merci ; baal ma = pardon ; waaw = oui ; déedéet = non ; nanga def = bonjour, comment vas-tu. Si tu n'es pas sûr d'un mot wolof, garde le mot français plutôt que d'inventer. Les noms d'événements, les dates, les lieux et les prix en FCFA restent EXACTEMENT ceux des données.\n"
        "- STYLE : ajoute quelques emojis pertinents et sobres (1 à 4 par réponse), par exemple 🎟️ billets, 🎶 concert, 🎉 soirée, ⚽ match, 🎭 théâtre, 📍 lieu, 📅 date, 💸 prix, 😊 pour rester chaleureux. Place-les en début de ligne ou en fin de phrase, jamais au milieu d'un mot, et n'en mets pas dans un message d'erreur ou de sécurité.\n"
        "- SORTIES ET IDÉES : quand la personne demande quoi faire, des idées de sorties, ce qui se passe, ce qui est populaire ou à la mode, propose 2 ou 3 événements pris dans la section « ÉVÉNEMENTS DISPONIBLES » (ceux marqués « à la une » et dont les billets sont disponibles d'abord), avec la date, le lieu et le prix, puis invite à ouvrir la page Événements. Ne présente jamais comme achetable un événement complet, aux ventes closes ou pas encore ouvertes ; tu peux le mentionner en le précisant. Si aucune liste n'est chargée, ne cite aucun événement précis.\n"
        "- Commence directement par l'essentiel, sans longue formule d'introduction.\n"
        "- Si la question est ambiguë, donne la meilleure réponse possible puis pose UNE seule question de précision.\n"
        "- Si la personne parle d'autre chose que Kcrowd (« bonjour », « j'ai faim », un conseil, une question générale), "
        "réponds avec gentillesse et utilité, comme un humain le ferait, puis, si c'est naturel, propose avec légèreté "
        "comment Kcrowd peut l'aider (par exemple chercher une sortie ou un événement). Ne la renvoie jamais "
        "sèchement vers Kcrowd. Refuse poliment seulement ce qui est dangereux ou illégal.\n"
        "- N'invente JAMAIS un chiffre, un nom d'événement précis, un prix, une date ou une donnée personnelle : "
        "ils viennent UNIQUEMENT de la section « DONNÉES RÉELLES » ou « ÉVÉNEMENTS DISPONIBLES » si elles sont présentes. Si tu ne connais pas une "
        "information (par exemple une politique de remboursement précise), dis-le honnêtement et conseille de "
        "contacter l'assistance via la page Contact.\n"
        "- N'écris jamais d'adresse web ni de lien : des boutons de navigation sont ajoutés automatiquement sous ta "
        "réponse. Tu peux nommer une page du menu (« la page Mes billets »).\n"
        "- N'utilise jamais un format « Champ : valeur » comme réponse."
        + bloc_donnees
        + bloc_evenements
        + bloc_contexte
    )


def terminer_proprement(texte: str) -> str:
    """Si la réponse a été coupée par la limite de longueur, on s'arrête à la dernière phrase complète."""
    texte = texte.strip()
    if not texte or texte[-1] in ".!?…)»":
        return texte
    fins = list(re.finditer(r"[.!?…]", texte))
    if fins and fins[-1].end() > len(texte) * 0.5:
        return texte[: fins[-1].end()]
    return texte


async def generer_reponse(role: str, prenom: str, message: str, donnees: list[str], historique: list[dict], evenements: list[str] | None = None) -> str:
    if not LLM_API_KEY:
        raise ErreurLLM("LLM_API_KEY n'est pas configurée (voir .env).")

    messages = [{"role": "system", "content": construire_prompt_systeme(role, prenom, donnees, evenements, detecter_langue(message))}]
    messages.extend(historique[-10:])
    messages.append({"role": "user", "content": message})

    modeles = [LLM_MODEL] + ([LLM_MODEL_SECOURS] if LLM_MODEL_SECOURS else [])
    if LLM_MODEL_WOLOF and detecter_langue(message) == "wo":
        modeles = [LLM_MODEL_WOLOF] + [m for m in modeles if m != LLM_MODEL_WOLOF]
    en_tetes = {"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"}
    derniere_erreur: Exception | None = None

    for tentative in range(NB_TENTATIVES):
        modele = modeles[min(tentative, len(modeles) - 1)] if tentative > 0 else modeles[0]
        corps = {"model": modele, "messages": messages, "max_tokens": MAX_TOKENS, "temperature": 0.6}
        if EFFORT:
            corps["reasoning_effort"] = EFFORT
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(DELAI_S)) as client:
                reponse = await client.post(LLM_BASE_URL, json=corps, headers=en_tetes)
        except httpx.RequestError as erreur:
            derniere_erreur = ErreurLLM(f"Fournisseur IA injoignable ({LLM_BASE_URL}) : {erreur!r}")
        else:
            if reponse.status_code == 200:
                try:
                    choix = reponse.json()["choices"][0]
                    contenu = (choix.get("message") or {}).get("content") or ""
                    fin = choix.get("finish_reason")
                except (ValueError, KeyError, IndexError, TypeError):
                    contenu, fin = "", None
                if contenu.strip() and REPONSE_PARASITE.search(contenu):
                    derniere_erreur = ErreurLLM(f"Réponse inutilisable du modèle {modele} : {contenu.strip()[:80]}")
                elif contenu.strip():
                    return terminer_proprement(contenu) if fin == "length" else contenu.strip()
                derniere_erreur = ErreurLLM("Le fournisseur IA a renvoyé une réponse vide.")
            elif reponse.status_code in (429, 500, 502, 503, 504):
                derniere_erreur = ErreurLLM(f"Le fournisseur IA a répondu {reponse.status_code} : {reponse.text[:200]}")
            else:
                raise ErreurLLM(f"Le fournisseur IA a répondu {reponse.status_code} : {reponse.text[:200]}")

        if tentative < NB_TENTATIVES - 1:
            await asyncio.sleep(1.5)

    raise derniere_erreur or ErreurLLM("Échec inconnu du fournisseur IA.")

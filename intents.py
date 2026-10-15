"""
Décide, à partir du message et du rôle, quelles données réelles aller
chercher — et calcule les totaux en Python (jamais l'IA : un compte ou une
somme calculés par un modèle de langage peut se tromper). L'IA ne fera que
mettre en phrase le résultat déjà calculé ici.

Les fonctions de calcul (compter_*, resumer_*) sont pures : elles prennent
des données déjà récupérées et ne font aucun appel réseau, donc testables
directement avec de fausses données.
"""

from __future__ import annotations

import logging

from dataclasses import dataclass
from typing import Awaitable, Callable

import django_client as dj

logger = logging.getLogger("chatbot.intents")


def _normaliser(texte: str) -> str:
    equivalences = str.maketrans("éèêëàâäîïôöùûüç", "eeeeaaaiioouuuc")
    return texte.lower().translate(equivalences)


def _contient_un_mot(message_normalise: str, mots: tuple[str, ...]) -> bool:
    return any(_normaliser(mot) in message_normalise for mot in mots)


# ── Calculs purs (aucun réseau) : les vrais totaux, jamais inventés ──

def resumer_billets(billets: list) -> str:
    if not billets:
        return "Cette personne n'a acheté aucun billet pour le moment."
    titres = ", ".join(sorted({b.get("ticketTypeName", "un billet") for b in billets})[:3])
    return f"{len(billets)} billet(s) achetés au total. Catégories : {titres}."


def resumer_favoris(favoris: list) -> str:
    return f"{len(favoris)} événement(s) en favoris."


def resumer_ventes_organisateur(transactions: list) -> str:
    reussies = [t for t in transactions if t.get("status") == "success"]
    total = sum(t.get("amount", 0) for t in reussies)
    return f"{len(reussies)} vente(s) réussie(s), pour un total de {total:,.0f} FCFA bruts.".replace(",", " ")


def resumer_solde_organisateur(solde: dict) -> str:
    montant = solde.get("solde", solde.get("montant", solde.get("amount", 0)))
    return f"Solde actuellement disponible à reverser : {montant:,.0f} FCFA.".replace(",", " ")


def resumer_evenements_organisateur(evenements: list) -> str:
    if not evenements:
        return "Cette personne n'a encore créé aucun événement."
    publies = sum(1 for e in evenements if e.get("status") == "published")
    return f"{len(evenements)} événement(s) au total, dont {publies} publié(s)."


def resumer_utilisateurs(utilisateurs: list) -> str:
    return f"{len(utilisateurs)} utilisateur(s) inscrit(s) sur la plateforme."


def resumer_organisateurs(organisateurs: list) -> str:
    return f"{len(organisateurs)} organisateur(s) enregistré(s) sur la plateforme."


def resumer_commission_totale(transactions: list) -> str:
    reussies = [t for t in transactions if t.get("status") == "success"]

    def commission_de(t: dict) -> float:
        if t.get("type") == "sponsored_ad":
            return t.get("amount", 0)
        return t.get("amount", 0) * 0.05

    total = sum(commission_de(t) for t in reussies)
    return f"Commission totale perçue par Kcrowd : {total:,.0f} FCFA.".replace(",", " ")


# ── Détection d'intention : quelle donnée aller chercher pour ce message ──

@dataclass(frozen=True)
class Intention:
    nom: str
    mots_cles: tuple[str, ...]
    recuperer: Callable[[str], Awaitable[object]]  # reçoit le jeton
    resumer: Callable[[object], str]


# ⚠️ Comme pour la navigation : billets et favoris personnels sont
# accessibles à TOUS les rôles, pas seulement aux utilisateurs simples.
INTENTIONS_COMMUNES: tuple[Intention, ...] = (
    Intention("billets", ("billet", "ticket", "achete", "acheté", "bileti"), dj.mes_billets, resumer_billets),
    Intention("favoris", ("favori", "aime", "coeur"), dj.mes_favoris, resumer_favoris),
)

INTENTIONS_ORGANIZER_SPECIFIQUES: tuple[Intention, ...] = (
    Intention("solde", ("solde", "revers", "virement", "retirer"), dj.mon_solde_organisateur, resumer_solde_organisateur),
    Intention("ventes", ("vente", "vendu", "recette", "chiffre d'affaires", "combien j'ai"), dj.mes_ventes_organisateur, resumer_ventes_organisateur),
    Intention("evenements", ("mes evenements", "combien d'evenement", "j'ai cree"), dj.mes_evenements_organisateur, resumer_evenements_organisateur),
)

INTENTIONS_ADMIN_SPECIFIQUES: tuple[Intention, ...] = (
    Intention("utilisateurs", ("combien d'utilisateur", "nombre d'utilisateur", "utilisateurs inscrits"), dj.tous_les_utilisateurs, resumer_utilisateurs),
    Intention("organisateurs", ("combien d'organisateur", "nombre d'organisateur"), dj.tous_les_organisateurs, resumer_organisateurs),
    Intention("commission", ("commission", "recette totale", "chiffre d'affaires plateforme"), dj.toutes_les_transactions, resumer_commission_totale),
)

_SPECIFIQUES_PAR_ROLE: dict[str, tuple[Intention, ...]] = {
    "organizer": INTENTIONS_ORGANIZER_SPECIFIQUES,
    "admin": INTENTIONS_ADMIN_SPECIFIQUES,
}


def detecter_intentions(message: str, role: str) -> list[Intention]:
    """Renvoie les intentions dont un mot-clé apparaît dans le message. Vide si aucune —
    dans ce cas, le chatbot répond sans donnée personnelle (question générale)."""
    texte = _normaliser(message)
    intentions = INTENTIONS_COMMUNES + _SPECIFIQUES_PAR_ROLE.get(role, ())
    return [i for i in intentions if _contient_un_mot(texte, i.mots_cles)]


async def construire_contexte_donnees(message: str, role: str, jeton: str) -> list[str]:
    """
    Pour chaque intention détectée : va chercher la vraie donnée, la résume en
    une phrase. Une intention qui échoue (Django indisponible) est ignorée
    plutôt que de faire planter toute la réponse du chatbot.
    """
    resumes: list[str] = []
    for intention in detecter_intentions(message, role):
        try:
            donnees = await intention.recuperer(jeton)
            resumes.append(intention.resumer(donnees))
        except dj.ErreurDjango as erreur:
            #  Avant, cette erreur disparaissait en silence — impossible de
            # savoir pourquoi une donnée manquait. Elle reste sans effet sur
            # la conversation (pas de plantage), mais est maintenant visible
            # dans le terminal FastAPI pour un vrai diagnostic.
            logger.warning("Échec de récupération pour l'intention %r : %s", intention.nom, erreur)
            continue
    return resumes
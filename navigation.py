"""
Liens de navigation par rôle. L'IA ne choisit JAMAIS un lien elle-même :
elle pourrait en inventer un qui n'existe pas. C'est ce module, par simple
recherche de mots-clés, qui décide quels liens proposer — toujours de vrais
chemins de l'application.

 Adaptez les "path" ci-dessous si vos routes réelles diffèrent.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class LienNav:
    label: str
    path: str
    mots_cles: tuple[str, ...]


#  Liens qu'un rôle possède TOUJOURS en plus des siens : un organisateur ou
# un administrateur peut aussi chercher des événements, avoir des billets ou
# des favoris personnels, exactement comme un simple utilisateur. Un premier
# oubli de cette règle avait laissé "Mes billets" invisible pour les
# organisateurs/admins ; ces liens communs évitent de refaire cette erreur à
# chaque nouveau lien ajouté plus tard.
LIENS_COMMUNS: tuple[LienNav, ...] = (
    LienNav("Rechercher des événements", "/evenements", ("evenement", "concert", "festival", "chercher", "trouver")),
    LienNav("Mes billets", "/compte/mes-billets", ("billet", "ticket", "achete", "acheté")),
    LienNav("Mes favoris", "/compte/favoris", ("favori", "aime", "coeur")),
    LienNav("Mon profil", "/compte/profil", ("profil", "compte", "coordonnee", "coordonnées")),
)

# Uniquement pour un simple utilisateur : proposer de DEVENIR organisateur n'a
# pas de sens pour quelqu'un qui l'est déjà.
LIENS_USER_SPECIFIQUES: tuple[LienNav, ...] = (
    LienNav("Devenir organisateur", "/devenir-organisateur", ("devenir organisateur", "creer un evenement", "organiser")),
)

LIENS_ORGANIZER_SPECIFIQUES: tuple[LienNav, ...] = (
    LienNav("Tableau de bord", "/organisateur", ("tableau de bord", "dashboard", "statistique", "chiffre")),
    LienNav("Mes événements", "/organisateur/evenements", ("mes evenements", "liste des evenements")),
    LienNav("Créer un événement", "/organisateur/evenements/nouveau", ("creer", "nouvel evenement", "publier", "organiser un evenement")),
    LienNav("Ventes & Billets", "/organisateur/ventes", ("vente", "vendu", "billet vendu", "recette", "chiffre d'affaires")),
    LienNav("Scanner de contrôle", "/organisateur/scanner", ("scanner", "scan", "controle", "entree")),
    LienNav("Campagnes & Pubs", "/organisateur/campagnes", ("campagne", "publicite", "pub", "sponsor")),
    LienNav("Reversements", "/organisateur/reversements", ("reversement", "solde", "virement", "wave", "orange money", "retirer")),
)

LIENS_ADMIN_SPECIFIQUES: tuple[LienNav, ...] = (
    LienNav("Tableau de bord", "/admin", ("tableau de bord", "dashboard", "statistique", "commission")),
    LienNav("Utilisateurs", "/admin/utilisateurs", ("utilisateur", "client", "suspendre", "compte")),
    LienNav("Organisateurs", "/admin/organisateurs", ("organisateur", "promoteur")),
    LienNav("Notifications", "/admin/notifications", ("notification", "alerte")),
    LienNav("Paramètres", "/admin/parametres", ("parametre", "reglage", "commission", "configuration")),
)

_SPECIFIQUES_PAR_ROLE: dict[str, tuple[LienNav, ...]] = {
    "user": LIENS_USER_SPECIFIQUES,
    "organizer": LIENS_ORGANIZER_SPECIFIQUES,
    "admin": LIENS_ADMIN_SPECIFIQUES,
}


def _normaliser(texte: str) -> str:
    """minuscules + suppression basique des accents, pour une recherche fiable."""
    equivalences = str.maketrans("éèêëàâäîïôöùûüç", "eeeeaaaiioouuuc")
    return texte.lower().translate(equivalences)


def liens_pour_role(role: str) -> tuple[LienNav, ...]:
    return LIENS_COMMUNS + _SPECIFIQUES_PAR_ROLE.get(role, LIENS_USER_SPECIFIQUES)


def trouver_liens(message: str, role: str, maximum: int = 2) -> list[LienNav]:
    """
    Cherche, parmi les liens autorisés pour CE rôle, ceux dont un mot-clé
    apparaît dans le message. Renvoie au plus `maximum` liens, triés par
    nombre de mots-clés trouvés (le plus pertinent en premier).
    Renvoie une liste vide si rien ne correspond — pas de lien au hasard.
    """
    texte = _normaliser(message)
    scores: list[tuple[int, LienNav]] = []

    for lien in liens_pour_role(role):
        score = sum(1 for mot in lien.mots_cles if _normaliser(mot) in texte)
        if score > 0:
            scores.append((score, lien))

    scores.sort(key=lambda paire: paire[0], reverse=True)
    return [lien for _score, lien in scores[:maximum]]
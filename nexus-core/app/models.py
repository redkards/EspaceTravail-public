"""Modèle de données (SQLAlchemy 2)."""
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def maintenant() -> datetime:
    """Horodatage UTC sans fuseau (stockage homogène SQLite / PostgreSQL)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Mission(Base):
    __tablename__ = "missions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    titre: Mapped[str] = mapped_column(String(200))
    consigne: Mapped[str] = mapped_column(Text)
    service: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # recue | en_cours | en_attente_n3 | validee | refusee | revision | terminee | echouee | suspendue
    statut: Mapped[str] = mapped_column(String(20), default="recue", index=True)
    niveau: Mapped[str | None] = mapped_column(String(2), nullable=True)  # N0..N3
    cree_le: Mapped[datetime] = mapped_column(DateTime, default=maintenant)
    maj_le: Mapped[datetime] = mapped_column(DateTime, default=maintenant, onupdate=maintenant)
    livrable_texte: Mapped[str | None] = mapped_column(Text, nullable=True)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    cout_eur: Mapped[float] = mapped_column(Float, default=0.0)
    # Champs complémentaires (hors SPEC) utiles au GATE et au cockpit.
    montant_eur: Mapped[float] = mapped_column(Float, default=0.0)
    action: Mapped[str | None] = mapped_column(String(40), nullable=True)
    directeur: Mapped[str | None] = mapped_column(String(40), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Code du projet (registre projets.yaml) ; « divers » par défaut.
    projet: Mapped[str] = mapped_column(String(40), default="divers", server_default="divers", index=True)
    # Niveau de fonctionnement (F1..F4) : demandé, appliqué (ne peut que monter) et raison.
    fonctionnement_demande: Mapped[str] = mapped_column(String(2), default="F2", server_default="F2")
    fonctionnement: Mapped[str] = mapped_column(String(2), default="F2", server_default="F2", index=True)
    fonctionnement_raison: Mapped[str | None] = mapped_column(Text, nullable=True)
    repli_f3: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    # Mesures : tokens entrée/sortie, durée cumulée (s), boucles de correction effectuées.
    tokens_entree: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    tokens_sortie: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    duree_s: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    revisions: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Attente particulière (ex. « lancement_f4 » : la mission attend l'accord avant de démarrer).
    attente: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # Relance automatique décidée par le directeur (une seule par mission).
    relance_auto: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Modèles réellement utilisés par rôle (JSON {role: modele}) et avertissements de charte (JSON).
    modeles_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    charte_avertissements: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[int | None] = mapped_column(Integer, nullable=True)  # note du propriétaire (1 à 5)


class Etape(Base):
    __tablename__ = "etapes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mission_id: Mapped[int] = mapped_column(ForeignKey("missions.id"), index=True)
    agent_id: Mapped[str] = mapped_column(String(60))
    role: Mapped[str] = mapped_column(String(20))
    entree: Mapped[str | None] = mapped_column(Text, nullable=True)
    sortie: Mapped[str | None] = mapped_column(Text, nullable=True)
    verdict: Mapped[str | None] = mapped_column(Text, nullable=True)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    cree_le: Mapped[datetime] = mapped_column(DateTime, default=maintenant)


class Decision(Base):
    __tablename__ = "decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mission_id: Mapped[int] = mapped_column(ForeignKey("missions.id"), index=True)
    niveau: Mapped[str] = mapped_column(String(2))
    # « livrable » (fiche N3 classique) ou « lancement_f4 » (accord avant un lancement payant).
    objet: Mapped[str] = mapped_column(String(20), default="livrable", server_default="livrable")
    resume: Mapped[str] = mapped_column(Text)
    recommandation: Mapped[str] = mapped_column(Text)
    cout_estime_eur: Mapped[float] = mapped_column(Float, default=0.0)
    risque: Mapped[str] = mapped_column(String(10))  # faible | moyen | eleve
    risque_raisons: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON : règles déclenchées
    sources: Mapped[str] = mapped_column(Text, default="")
    avis_checker: Mapped[str] = mapped_column(Text, default="")
    # en_attente | validee | refusee | revision | expiree
    statut: Mapped[str] = mapped_column(String(12), default="en_attente", index=True)
    cree_le: Mapped[datetime] = mapped_column(DateTime, default=maintenant)
    decide_le: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    commentaire: Mapped[str | None] = mapped_column(Text, nullable=True)


class Ledger(Base):
    """Journal append-only chaîné par SHA-256 (aucune route de modification)."""
    __tablename__ = "ledger"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    horodatage: Mapped[str] = mapped_column(String(32))  # ISO 8601 UTC, inclus dans le hash
    acteur: Mapped[str] = mapped_column(String(60))
    action: Mapped[str] = mapped_column(String(60))
    mission_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    hash_prec: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))
    # « hmac » : HMAC-SHA256 avec LEDGER_HMAC_KEY ; « sha256 » : chaînage sans clé (ancien mode).
    algo: Mapped[str] = mapped_column(String(10), default="sha256", server_default="sha256")


class Etat(Base):
    """Clé / valeur : kill switch et compteurs de budget."""
    __tablename__ = "etat"
    cle: Mapped[str] = mapped_column(String(120), primary_key=True)
    valeur: Mapped[str] = mapped_column(Text, default="")


class Connaissance(Base):
    """Connaissance d'un projet (mémoire) ; index plein texte FTS5 créé par memoire.initialiser_fts."""
    __tablename__ = "connaissances"
    __table_args__ = (UniqueConstraint("projet", "source", name="uq_connaissance_projet_source"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    projet: Mapped[str] = mapped_column(String(40), index=True)
    titre: Mapped[str] = mapped_column(String(200))
    contenu: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(300))
    date: Mapped[datetime] = mapped_column(DateTime, default=maintenant)
    auteur: Mapped[str] = mapped_column(String(60))
    version: Mapped[int] = mapped_column(Integer, default=1)
    origine: Mapped[str] = mapped_column(String(10), default="manuel")  # manuel | import | auto
    empreinte: Mapped[str] = mapped_column(String(64))


class Exemple(Base):
    """Livrable modèle d'un service (few-shot) ; au plus 3 actifs par service."""
    __tablename__ = "exemples"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mission_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    service: Mapped[str] = mapped_column(String(80), index=True)
    projet: Mapped[str | None] = mapped_column(String(40), nullable=True)
    titre: Mapped[str] = mapped_column(String(200))
    extrait: Mapped[str] = mapped_column(Text)
    note: Mapped[int | None] = mapped_column(Integer, nullable=True)
    origine: Mapped[str] = mapped_column(String(20))  # validation_n3 | note | manuel
    actif: Mapped[bool] = mapped_column(Boolean, default=True)
    cree_le: Mapped[datetime] = mapped_column(DateTime, default=maintenant)


class ExportQG(Base):
    """File d'export vers le QG (webhook signé) ; une entrée par mission."""
    __tablename__ = "export_qg"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mission_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    charge_json: Mapped[str] = mapped_column(Text)
    statut: Mapped[str] = mapped_column(String(12), default="en_attente", index=True)  # en_attente | envoye | echec
    tentatives: Mapped[int] = mapped_column(Integer, default=0)
    prochain_essai: Mapped[datetime] = mapped_column(DateTime, default=maintenant)
    derniere_erreur: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cree_le: Mapped[datetime] = mapped_column(DateTime, default=maintenant)
    envoye_le: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ArchiveIndex(Base):
    """Index de l'archive immuable (une ligne par enregistrement ; texte court pour la recherche FTS5)."""
    __tablename__ = "archive_index"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    mois: Mapped[str] = mapped_column(String(7))
    mission_id: Mapped[int] = mapped_column(Integer, index=True)
    evenement: Mapped[str] = mapped_column(String(30))
    projet: Mapped[str | None] = mapped_column(String(40), nullable=True)
    service: Mapped[str | None] = mapped_column(String(80), nullable=True)
    statut: Mapped[str | None] = mapped_column(String(20), nullable=True)
    hash: Mapped[str] = mapped_column(String(64))
    prec: Mapped[str] = mapped_column(String(64))
    texte: Mapped[str] = mapped_column(Text, default="")
    efface: Mapped[bool] = mapped_column(Boolean, default=False)
    cree_le: Mapped[datetime] = mapped_column(DateTime, default=maintenant)


class Lecon(Base):
    """Leçon apprise : candidate → proposée (≥ seuil) → acceptée / rejetée ; suspendue si régression."""
    __tablename__ = "lecons"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cle: Mapped[str] = mapped_column(String(200), unique=True, index=True)  # signature normalisée + portée
    service: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    projet: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    texte: Mapped[str] = mapped_column(String(200))
    texte_llm: Mapped[str | None] = mapped_column(String(200), nullable=True)  # reformulation (marquée)
    type: Mapped[str] = mapped_column(String(12))  # interdit | obligation | methode
    origine: Mapped[str] = mapped_column(String(20))  # checker | charte | decideur | plafond | directeur
    statut: Mapped[str] = mapped_column(String(12), default="candidate", index=True)
    occurrences: Mapped[int] = mapped_column(Integer, default=0)
    sources_json: Mapped[str] = mapped_column(Text, default="[]")  # ids des missions (au plus 50)
    premiere: Mapped[datetime] = mapped_column(DateTime, default=maintenant)
    derniere: Mapped[datetime] = mapped_column(DateTime, default=maintenant)
    proposee_le: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decidee_le: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    note_activation: Mapped[float | None] = mapped_column(Float, nullable=True)
    semaine_activation: Mapped[str | None] = mapped_column(String(10), nullable=True)
    suspendue_le: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    motif: Mapped[str | None] = mapped_column(Text, nullable=True)  # motif de rejet / suspension

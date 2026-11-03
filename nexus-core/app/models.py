"""Modèle de données (SQLAlchemy 2)."""
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
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


class Etat(Base):
    """Clé / valeur : kill switch et compteurs de budget."""
    __tablename__ = "etat"
    cle: Mapped[str] = mapped_column(String(120), primary_key=True)
    valeur: Mapped[str] = mapped_column(Text, default="")

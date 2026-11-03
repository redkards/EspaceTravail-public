"""File d'exécution des missions : nombre limité de missions simultanées, ordre FIFO.

NEXUS_MAX_MISSIONS (défaut : 1 avec un modèle local, 2 sinon) borne les missions qui tournent
en même temps ; les suivantes attendent leur tour, statut visible « en_attente_place ».
"""
import logging
import os
import threading
from collections import deque

log = logging.getLogger("nexus.file")


def capacite() -> int:
    v = os.environ.get("NEXUS_MAX_MISSIONS", "").strip()
    if v:
        try:
            return max(1, int(v))
        except ValueError:
            log.warning("NEXUS_MAX_MISSIONS invalide (%s) : valeur par défaut utilisée.", v)
    from .llm import info
    return 1 if info()["fournisseur"] in ("ollama", "fake") else 2


class FileMissions:
    def __init__(self):
        self._cond = threading.Condition()
        self._attente: deque = deque()
        self._actifs: set = set()

    def etat(self) -> dict:
        with self._cond:
            return {"capacite": capacite(), "en_cours": sorted(self._actifs), "en_attente": list(self._attente)}

    def _reserver(self, mid: int) -> None:
        with self._cond:
            self._attente.append(mid)

    def _attendre_et_executer(self, mid: int, fonction, *args) -> None:
        from . import ledger, pipeline
        signale = False
        with self._cond:
            while not (self._attente[0] == mid and len(self._actifs) < capacite()):
                if not signale:
                    position = list(self._attente).index(mid) + 1
                    occupees = len(self._actifs)
                    self._cond.release()
                    try:  # écriture hors verrou
                        if pipeline.transition(mid, ("recue",), "en_attente_place",
                                               message=f"En attente de place : {occupees} mission(s) en cours, "
                                                       f"position {position} dans la file."):
                            ledger.journaliser("NEXUS-PRIME", "mission_en_attente_place", mid, position=position)
                    finally:
                        self._cond.acquire()
                    signale = True
                    continue
                self._cond.wait(timeout=1.0)
            self._attente.popleft()
            self._actifs.add(mid)
        try:
            fonction(mid, *args)
        except Exception:
            log.exception("Erreur non rattrapée dans la mission %s", mid)
        finally:
            with self._cond:
                self._actifs.discard(mid)
                self._cond.notify_all()

    def executer(self, mid: int, fonction, *args) -> None:
        """Exécute dans le fil courant après avoir attendu son tour (tâches de fond FastAPI)."""
        self._reserver(mid)
        self._attendre_et_executer(mid, fonction, *args)

    def soumettre(self, mid: int, fonction, *args) -> threading.Thread:
        """Réserve la place dans l'ordre d'appel puis exécute dans un fil dédié (reprise au démarrage)."""
        self._reserver(mid)
        fil = threading.Thread(target=self._attendre_et_executer, args=(mid, fonction, *args),
                               name=f"mission-{mid}", daemon=True)
        fil.start()
        return fil

    def attendre_vide(self, delai_s: float = 30.0) -> bool:
        """Attend que la file soit vide (tests, arrêt)."""
        with self._cond:
            return self._cond.wait_for(lambda: not self._attente and not self._actifs, timeout=delai_s)


FILE = FileMissions()

"""Surcharges propres au fil d'exécution courant (test fantôme) : jamais globales.

Le test fantôme rejoue des missions « après » avec une variante (leçon, exemple, charte, modèles
par rôle) sans modifier la configuration réelle ni les autres fils (missions normales).
"""
import threading
from contextlib import contextmanager

_local = threading.local()


def lire(cle: str):
    return getattr(_local, "valeurs", {}).get(cle)


@contextmanager
def appliquer(**valeurs):
    ancien = getattr(_local, "valeurs", {})
    _local.valeurs = {**ancien, **{k: v for k, v in valeurs.items() if v is not None}}
    try:
        yield
    finally:
        _local.valeurs = ancien

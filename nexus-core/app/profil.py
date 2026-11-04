"""Profil matériel (NEXUS_PROFIL_MATERIEL = kvm2 | kvm4 | kvm8 ; défaut kvm2, calibrage actuel).

Ne change que des valeurs PAR DÉFAUT : une variable explicite (NEXUS_MAX_MISSIONS, NEXUS_FANTOME_K…)
l'emporte toujours. kvm2 = 2 vCPU / 8 Go (Hostinger KVM 2), kvm4 = 4 vCPU / 16 Go, kvm8 = 8 vCPU / 32 Go.
Les limites mémoire des conteneurs restent dans docker-compose (INFRA).
"""
import os

PROFILS = {
    "kvm2": {"missions_local": 1, "missions_cloud": 2, "fantome_k": 5},
    "kvm4": {"missions_local": 2, "missions_cloud": 3, "fantome_k": 8},
    "kvm8": {"missions_local": 3, "missions_cloud": 5, "fantome_k": 10},
}


def nom() -> str:
    v = os.environ.get("NEXUS_PROFIL_MATERIEL", "").strip().lower()
    return v if v in PROFILS else "kvm2"


def valeur(cle: str) -> int:
    return PROFILS[nom()][cle]

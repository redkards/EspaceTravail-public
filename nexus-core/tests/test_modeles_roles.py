"""V2 B1 — modèles par rôle, diversité du contrôle, repli, modèles réellement utilisés."""
import httpx
import pytest

from app import pipeline
from app.llm import FournisseurOllamaCloud, info, modele_pour, modeles_roles

from .conftest import creer_mission, lire_mission


@pytest.fixture
def cloud(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama_cloud")
    monkeypatch.setenv("OLLAMA_API_KEY", "cle-test")
    for v in ("NEXUS_MODEL", "NEXUS_MODEL_CHECKER", "NEXUS_MODELES_ROLES", "NEXUS_MODELES_CLOUD"):
        monkeypatch.delenv(v, raising=False)


def test_configuration_par_role_et_par_fournisseur(monkeypatch):
    monkeypatch.setenv("NEXUS_MODELES_ROLES", "collector=gemma4:31b, analyst=gemma4:31b, checker=qwen3:8b,"
                                              "checker@ollama_cloud=gpt-oss:120b, inconnu=x, directeur=")
    assert modeles_roles("ollama") == {"collector": "gemma4:31b", "analyst": "gemma4:31b", "checker": "qwen3:8b"}
    assert modeles_roles("ollama_cloud")["checker"] == "gpt-oss:120b"
    assert modele_pour("checker", None, "ollama_cloud") == "gpt-oss:120b"
    assert modele_pour("analyst", "fiche:7b", "ollama_cloud") == "fiche:7b"  # la fiche agent l'emporte


def test_diversite_par_defaut_en_cloud(cloud):
    assert modele_pour("analyst", None, "ollama_cloud") == "gemma4:31b"
    assert modele_pour("checker", None, "ollama_cloud") == "gpt-oss:120b"  # différent de l'ANALYST
    i = info()
    assert i["modeles_roles"]["checker"] != i["modeles_roles"]["analyst"] and i["controle_diversifie"] is True


def test_diversite_impossible_si_un_seul_modele(cloud, monkeypatch):
    monkeypatch.setenv("NEXUS_MODELES_CLOUD", "gemma4:31b")
    assert modele_pour("checker", None, "ollama_cloud") == "gemma4:31b"
    assert info()["controle_diversifie"] is False


def test_checker_explicite_prioritaire(cloud, monkeypatch):
    monkeypatch.setenv("NEXUS_MODEL_CHECKER", "qwen3:8b")
    assert modele_pour("checker", None, "ollama_cloud") == "qwen3:8b"


def test_local_sans_diversite(monkeypatch):
    monkeypatch.delenv("NEXUS_MODELES_ROLES", raising=False)
    assert modele_pour("checker", None, "ollama") == modele_pour("analyst", None, "ollama")


def test_repli_si_modele_de_role_indisponible(cloud, monkeypatch):
    appels = []

    def faux_post(url, json=None, headers=None, timeout=None, **_):
        appels.append(json["model"])
        if json["model"] == "gpt-oss:120b":
            return httpx.Response(404, json={"error": "model not found"}, request=httpx.Request("POST", url))
        return httpx.Response(200, json={"message": {"content": '{"ok": true, "problemes": []}'}, "eval_count": 3},
                              request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "post", faux_post)
    r = FournisseurOllamaCloud().appeler("s", "u", role="checker")
    assert appels == ["gpt-oss:120b", "gemma4:31b"] and r.modele == "gemma4:31b"
    assert "indisponible" in r.bascule


def test_modeles_utilises_enregistres(client, entetes):
    mid = client.post("/api/missions", headers=entetes, json={"titre": "Checklist", "consigne": "Liste les étapes",
                                                             "service": "OPS-CORE/projets"}).json()["id"]
    m = client.get(f"/api/missions/{mid}", headers=entetes).json()
    assert {"collector", "analyst", "checker", "gate"} <= set(m["modeles"])
    assert all(v.startswith("fake:") for v in m["modeles"].values())
    assert "modeles_roles" in client.get("/api/sante").json()["llm"]


def test_double_controle_trace_separement():
    mid = creer_mission(titre="Checklist", consigne="Liste les étapes", service="OPS-CORE/projets",
                        fonctionnement="F3")
    pipeline.traiter(mid)
    import json
    assert "checker_local" in json.loads(lire_mission(mid).modeles_json)

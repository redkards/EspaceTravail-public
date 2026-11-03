"""Ollama Cloud : en-tête Bearer, repli local sur 429, clé jamais exposée, garde-fou gratuit."""
import httpx
import pytest

from app import ledger, pipeline
from app.llm import ErreurLLM, FournisseurOllama, FournisseurOllamaCloud, fournisseur, info

from .conftest import creer_mission, lire_mission

CLE_CLOUD = "sk-ollama-secret-123"


class FauxReseau:
    """Remplace httpx.post / httpx.get ; enregistre les appels."""

    def __init__(self, statut_cloud=200, local_ok=True):
        self.statut_cloud = statut_cloud
        self.local_ok = local_ok
        self.appels = []

    def _rep(self, statut, url, json_=None):
        return httpx.Response(statut, json=json_ or {}, request=httpx.Request("POST", url))

    def post(self, url, json=None, headers=None, timeout=None, **_):
        self.appels.append({"url": url, "headers": dict(headers or {}), "corps": json})
        if url.startswith("https://ollama.com"):
            if self.statut_cloud != 200:
                return self._rep(self.statut_cloud, url, {"error": "limite"})
            return self._rep(200, url, {"message": {"content": "réponse cloud"},
                                        "prompt_eval_count": 10, "eval_count": 5})
        if not self.local_ok:
            raise httpx.ConnectError("local injoignable")
        role_checker = (json or {}).get("format") == "json"
        contenu = '{"ok": true, "problemes": []}' if role_checker else "réponse locale"
        return self._rep(200, url, {"message": {"content": contenu}, "eval_count": 7})

    def get(self, url, timeout=None, **_):
        if not self.local_ok:
            raise httpx.ConnectError("local injoignable")
        return httpx.Response(200, json={"models": []}, request=httpx.Request("GET", url))


@pytest.fixture
def cloud(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama_cloud")
    monkeypatch.setenv("OLLAMA_API_KEY", CLE_CLOUD)
    monkeypatch.setenv("OLLAMA_URL", "http://ollama-local:11434")
    monkeypatch.delenv("NEXUS_MODEL", raising=False)

    def installer(**kw):
        r = FauxReseau(**kw)
        monkeypatch.setattr(httpx, "post", r.post)
        monkeypatch.setattr(httpx, "get", r.get)
        return r
    return installer


def test_entete_bearer_et_modele_par_defaut(cloud):
    reseau = cloud()
    r = fournisseur().appeler("sys", "question", role="analyst")
    appel = reseau.appels[0]
    assert appel["url"] == "https://ollama.com/api/chat"
    assert appel["headers"]["Authorization"] == f"Bearer {CLE_CLOUD}"
    assert appel["corps"]["model"] == "gemma4:31b" and appel["corps"]["stream"] is False
    assert r.texte == "réponse cloud" and r.tokens == 15 and r.bascule is None


def test_modele_checker_dedie(cloud, monkeypatch):
    monkeypatch.setenv("NEXUS_MODEL_CHECKER", "qwen3:8b")
    reseau = cloud()
    fournisseur().appeler("sys", "q", role="checker")
    fournisseur().appeler("sys", "q", role="analyst")
    assert reseau.appels[0]["corps"]["model"] == "qwen3:8b"
    assert reseau.appels[0]["corps"]["format"] == "json"
    assert reseau.appels[1]["corps"]["model"] == "gemma4:31b"


def test_bascule_locale_sur_429(cloud):
    reseau = cloud(statut_cloud=429)
    r = fournisseur().appeler("sys", "q", role="analyst")
    cloud_appels = [a for a in reseau.appels if a["url"].startswith("https://ollama.com")]
    assert len(cloud_appels) == 2  # un nouvel essai avant la bascule
    assert reseau.appels[-1]["url"] == "http://ollama-local:11434/api/chat"
    assert "Authorization" not in reseau.appels[-1]["headers"]  # clé jamais envoyée au local
    assert r.fournisseur == "ollama" and r.texte == "réponse locale"
    assert "HTTP 429" in r.bascule


def test_sans_repli_erreur(cloud, monkeypatch):
    monkeypatch.setenv("LLM_FALLBACK", "aucun")
    cloud(statut_cloud=503)
    with pytest.raises(ErreurLLM) as e:
        fournisseur().appeler("sys", "q")
    assert CLE_CLOUD not in str(e.value)


def test_local_injoignable_etape_en_erreur(cloud):
    cloud(statut_cloud=500, local_ok=False)
    mid = creer_mission(titre="Checklist", consigne="Liste les étapes", service="OPS-CORE/projets")
    pipeline.traiter(mid)
    assert lire_mission(mid).statut == "echouee"
    assert "erreur_llm" in [e["action"] for e in ledger.lister(50)]


def test_bascule_journalisee_sans_cle(cloud):
    cloud(statut_cloud=429)
    mid = creer_mission(titre="Checklist", consigne="Liste les étapes", service="OPS-CORE/projets")
    pipeline.traiter(mid)
    assert lire_mission(mid).statut == "terminee"
    entrees = ledger.lister(200)
    assert "bascule_llm" in [e["action"] for e in entrees]
    assert CLE_CLOUD not in repr(entrees)


def test_cle_absente_des_sorties_api(cloud, client, entetes):
    cloud()
    for url, h in (("/api/sante", {}), ("/api/sante", entetes), ("/api/budget", entetes),
                   ("/cockpit/api/sante", {"X-Cockpit-Auth": "secret-interne-caddy-de-test"}), ("/api/ledger?limit=100", entetes)):
        r = client.get(url, headers=h)
        assert r.status_code == 200 and CLE_CLOUD not in r.text
    llm = client.get("/api/sante").json()["llm"]
    assert llm["fournisseur"] == "ollama_cloud" and llm["modele"] == "gemma4:31b"


def test_cloud_sans_cle_utilise_local(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama_cloud")
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    f = fournisseur()
    assert isinstance(f, FournisseurOllama) and info()["modele"] == "qwen2.5:3b"


def test_garde_fou_anthropic_budget_zero(monkeypatch, client):
    """BUDGET_MONTHLY_EUR=0 + anthropic → refusé, bascule vers un fournisseur gratuit."""
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("BUDGET_MONTHLY_EUR", "0")
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    assert isinstance(fournisseur(), FournisseurOllama)
    monkeypatch.setenv("OLLAMA_API_KEY", CLE_CLOUD)
    monkeypatch.delenv("NEXUS_MODEL", raising=False)
    f = fournisseur()
    assert isinstance(f, FournisseurOllamaCloud) and f.modele_force == "gemma4:31b"
    # Au démarrage : refus journalisé avec un message clair.
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        llm = c.get("/api/sante").json()["llm"]
    assert llm["fournisseur"] == "ollama_cloud" and llm["fournisseur_demande"] == "anthropic"
    refus = [e for e in ledger.lister(50) if e["action"] == "fournisseur_refuse"]
    assert refus and "BUDGET_MONTHLY_EUR=0" in refus[0]["details"]["motif"]


def test_cout_nul_par_defaut():
    from app import budget
    assert budget.cout_eur(10000, "ollama_cloud") == 0.0
    assert budget.fournisseur_payant("ollama_cloud") is False

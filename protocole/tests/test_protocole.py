"""Protocole NEXUS v1 : schémas, moteur de validation, exemples réels (nexus-core LLM factice, nexus-bridge)."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROTOCOLE = Path(__file__).resolve().parent.parent
RACINE = PROTOCOLE.parent
sys.path.insert(0, str(PROTOCOLE))
import valider as V  # noqa: E402

MOTEURS = ["interne"] + (["jsonschema"] if V.jsonschema_disponible() else [])


def exemples(dossier: Path):
    for f in sorted(dossier.glob("*.json")):
        if f.name.startswith("_"):
            continue
        cible = f.name.split("__")[0].replace("@", "#")
        yield cible, f.name, json.loads(f.read_text(encoding="utf-8"))


def tout_valider(dossier: Path, moteur: str) -> dict:
    erreurs = {}
    for cible, nom, obj in exemples(dossier):
        e = V.valider(obj, cible, moteur)
        if e:
            erreurs[nom] = e[:5]
        if cible == "mission":
            e = V.valider(V.livrable_depuis_mission(obj), "livrable", moteur)
            if e:
                erreurs[f"livrable de {nom}"] = e[:5]
    return erreurs


def produire(composant: str, sortie: Path):
    p = subprocess.run([sys.executable, str(PROTOCOLE / "produire_exemples.py"), composant, str(sortie)],
                       capture_output=True, text=True, timeout=300)
    assert p.returncode == 0, p.stderr[-3000:]


# --------------------------------------------------------------------------- schémas
def test_version_semver():
    assert (PROTOCOLE / "VERSION").read_text().strip() == V.VERSION
    assert V.VERSION.split(".")[0] == "1" and len(V.VERSION.split(".")) == 3


def test_schemas_coherents():
    assert V.verifier_schemas() == []
    for uri, s in V.schemas().items():
        assert uri.endswith(".schema.json") and s["$schema"].endswith("2020-12/schema")


def test_cibles_principales_presentes():
    c = set(V.cibles())
    for attendu in ("mission", "mission-creation", "mission-creation-reponse", "etape", "decision", "livrable",
                    "connaissance", "agent", "evenement-ledger", "sante", "fonctionnement",
                    "mcp-outils#mothership_mission.entree", "mcp-outils#mothership_mission.sortie"):
        assert attendu in c, attendu
    with pytest.raises(V.SchemaInconnu):
        V.valider({}, "inexistant")


@pytest.mark.parametrize("moteur", MOTEURS)
def test_exemples_figes(moteur):
    """Instantané versionné (protocole/exemples) : sert aussi quand nexus-core n'est pas dans le dépôt."""
    assert len(list(exemples(PROTOCOLE / "exemples"))) > 50
    assert tout_valider(PROTOCOLE / "exemples", moteur) == {}


# --------------------------------------------------------------------------- refus attendus
INVALIDES = [
    ("mission-creation", {"consigne": "x"}),                                     # titre absent
    ("mission-creation", {"titre": "", "consigne": "x"}),                        # titre vide
    ("mission-creation", {"titre": "a", "consigne": "b", "fonctionnement": "F5"}),
    ("mission-creation", {"titre": "a", "consigne": "b", "action": "Payer!"}),   # motif
    ("mission-creation", {"titre": "a", "consigne": "b", "montant_eur": -1}),
    ("decision", {"id": 1}),
    ("evenement-ledger", {"id": 1, "horodatage": "2026-11-03T10:00:00", "acteur": "API", "action": "x",
                          "details": {}, "hash_prec": "0" * 64, "hash": "z" * 64, "algo": "sha256"}),
    ("agent", {"id": "X", "nom": "n", "role": "pdg", "direction": "D", "departement": "d", "service": "",
               "mission": "m", "consignes": "c", "outils_autorises": []}),
    ("mcp-outils#memoire_ecrire.entree", {"sujet": "s", "contenu": "c", "etiquettes": [], "inconnu": 1}),
    ("mcp-outils#tache_creer.entree", {"titre": "t", "description": "", "assigne_a": "personne"}),
    ("mcp-outils#memoire_chercher.entree", {"requete": "x", "limite": 0}),
    ("mcp-outils#memoire_chercher.entree", {"requete": "x", "limite": True}),    # booléen ≠ entier
    ("sante", {"statut": "ok", "service": "autre", "llm": {"fournisseur": "f", "modele": "m"}}),
    ("mission#liste", [{"id": 0}]),
]


@pytest.mark.parametrize("moteur", MOTEURS)
@pytest.mark.parametrize("cible,obj", INVALIDES)
def test_invalides_refuses(moteur, cible, obj):
    assert V.valider(obj, cible, moteur), (cible, obj)


@pytest.mark.parametrize("moteur", MOTEURS)
def test_champs_inconnus_ignores_en_lecture(moteur):
    """Compatibilité ascendante : un champ ajouté par une version 1.x future ne casse pas un client 1.0."""
    s = json.loads((PROTOCOLE / "exemples" / "sante__ok.json").read_text())
    s["champ_futur"] = {"quoi": 1}
    assert V.valider(s, "sante", moteur) == []
    m = json.loads((PROTOCOLE / "exemples" / "mission__n1_service.json").read_text())
    m["statut"] = "statut_futur"  # statut ouvert (motif), pas une énumération fermée
    assert V.valider(m, "mission", moteur) == []


# --------------------------------------------------------------------------- exemples réels
CORE = RACINE / "nexus-core" / "app" / "main.py"
BRIDGE = RACINE / "nexus-bridge" / "app" / "main.py"


@pytest.fixture(scope="module")
def reels(tmp_path_factory):
    d = tmp_path_factory.mktemp("exemples")
    if CORE.exists():
        pytest.importorskip("fastapi")
        pytest.importorskip("sqlalchemy")
        produire("core", d)
    else:  # dépôt nexus-bridge séparé : on rejoue l'instantané de nexus-core
        for f in (PROTOCOLE / "exemples").glob("*.json"):
            if not f.name.startswith("mcp-outils"):
                (d / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    if BRIDGE.exists():
        produire("bridge", d)
    return d


@pytest.mark.parametrize("moteur", MOTEURS)
def test_exemples_reels_conformes(reels, moteur):
    noms = {n for _, n, _ in exemples(reels)}
    if CORE.exists():
        assert {"sante__ok.json", "mission__n1_service.json", "decision__devis.json",
                "evenement-ledger@verification__ok.json"} <= noms
    if BRIDGE.exists():
        assert "mcp-outils@mothership_statut.sortie__mothership_statut.json" in noms
        assert "mcp-outils@erreur__parametre_inconnu.json" in noms
    assert tout_valider(reels, moteur) == {}


@pytest.mark.skipif(not CORE.exists(), reason="nexus-core absent de ce dépôt")
def test_exemples_reels_couvrent_les_objets(reels):
    cibles = {c for c, _, _ in exemples(reels)}
    for c in ("mission", "mission-creation", "mission-creation-reponse", "etape", "decision", "decision#actionReponse",
              "connaissance", "connaissance#ajoutReponse", "agent#liste", "evenement-ledger", "sante", "fonctionnement"):
        assert c in cibles, c
    m = json.loads((reels / "mission__n1_service.json").read_text())
    assert m["etapes"] and m["fonctionnement"] == "F1"
    f4 = json.loads((reels / "mission-creation-reponse__f4_lancement.json").read_text())
    assert f4["statut"] == "en_attente_n3" and f4["decision_id"] >= 1
    assert json.loads((reels / "mission__devis_valide.json").read_text())["statut"] == "validee"


@pytest.mark.skipif(not CORE.exists(), reason="nexus-core absent de ce dépôt")
def test_fiches_agents_yaml():
    yaml = pytest.importorskip("yaml")
    fiches = sorted((RACINE / "nexus-core" / "agents").glob("*.yaml"))
    assert len(fiches) >= 93
    for moteur in MOTEURS:
        ko = {f.name: e for f in fiches if (e := V.valider(yaml.safe_load(f.read_text(encoding="utf-8")), "agent", moteur))}
        assert ko == {}


@pytest.mark.skipif(not BRIDGE.exists(), reason="nexus-bridge absent de ce dépôt")
def test_entrees_mcp_synchronisees_avec_la_passerelle():
    """Les schémas d'entrée du protocole correspondent aux schémas réellement servis par tools/list."""
    code = ("import json,sys; sys.dont_write_bytecode=True; sys.path.insert(0,'.'); from app import outils; "
            "print(json.dumps({o.nom: o.schema for o in outils.outils()}))")
    p = subprocess.run([sys.executable, "-c", code], cwd=RACINE / "nexus-bridge", capture_output=True, text=True,
                       timeout=60)
    assert p.returncode == 0, p.stderr
    reels_ = json.loads(p.stdout)
    proto = V.schemas()[V.uri_cible("mcp-outils").split("#")[0]]
    assert sorted(reels_) == proto["x-outils"]
    for nom, s in reels_.items():
        e = proto["$defs"][f"{nom}.entree"]
        assert set(e["properties"]) == set(s["properties"]), nom
        assert e["required"] == s["required"] and e.get("additionalProperties") == s.get("additionalProperties"), nom
        for cle, ps in s["properties"].items():
            if cle == "projet":
                continue  # liste dynamique (BRIDGE_PROJETS) remplacée par le motif codeProjet
            pe = e["properties"][cle]
            for k in ("type", "enum", "minimum", "maximum", "maxLength", "minLength", "maxItems", "pattern"):
                assert pe.get(k) == ps.get(k), (nom, cle, k)


# --------------------------------------------------------------------------- ligne de commande
def test_cli(tmp_path):
    ok = tmp_path / "ok.json"
    ok.write_text(json.dumps({"titre": "a", "consigne": "b"}))
    ko = tmp_path / "ko.json"
    ko.write_text(json.dumps({"titre": "a"}))
    cmd = [sys.executable, str(PROTOCOLE / "valider.py")]
    assert subprocess.run(cmd + ["mission-creation", str(ok), "--moteur", "interne"]).returncode == 0
    p = subprocess.run(cmd + ["mission-creation", str(ko), "--moteur", "interne"], capture_output=True, text=True)
    assert p.returncode == 1 and "consigne" in p.stdout
    assert subprocess.run(cmd + ["--verifier-schemas"], capture_output=True).returncode == 0
    p = subprocess.run(cmd + ["--liste"], capture_output=True, text=True)
    assert "mcp-outils#journal_lister.sortie" in p.stdout

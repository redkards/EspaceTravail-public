#!/usr/bin/env python3
"""Validation d'objets JSON contre le Protocole NEXUS v1 (protocole/schemas/*.schema.json).

Deux moteurs :
- « interne » : Python standard uniquement, sous-ensemble de JSON Schema 2020-12 suffisant pour ces
  schémas ($ref local et entre fichiers, type, enum, const, properties, required,
  additionalProperties, items, min/maxItems, min/maxLength, pattern, minimum, maximum,
  exclusiveMinimum, anyOf, allOf, oneOf, not) ;
- « jsonschema » : la bibliothèque jsonschema (≥ 4.18) si elle est installée — validation complète.
« auto » (défaut) choisit jsonschema s'il est importable, sinon le moteur interne.

Cibles : « mission », « decision#liste », « mcp-outils#memoire_ecrire.sortie »…
(nom du fichier sans « .schema.json », puis éventuellement « #<clé de $defs> »).

Utilisation :
  python3 valider.py mission exemple.json [autre.json…]   # code 0 si tout est valide
  python3 valider.py --agents ../nexus-core/agents          # fiches YAML (PyYAML requis)
  python3 valider.py --verifier-schemas                     # cohérence des schémas eux-mêmes
  python3 valider.py --liste                                # cibles disponibles
Options : --moteur auto|interne|jsonschema
"""
import argparse
import json
import math
import re
import sys
from functools import lru_cache
from pathlib import Path
from urllib.parse import urldefrag, urljoin

DOSSIER = Path(__file__).resolve().parent
SCHEMAS = DOSSIER / "schemas"
VERSION = (DOSSIER / "VERSION").read_text(encoding="utf-8").strip() if (DOSSIER / "VERSION").exists() else "1.0.0"

# Mots-clés appliqués par le moteur interne ; les autres doivent être de pures annotations.
APPLIQUES = {"$ref", "type", "enum", "const", "properties", "required", "additionalProperties", "items",
             "minItems", "maxItems", "minLength", "maxLength", "pattern", "minimum", "maximum",
             "exclusiveMinimum", "anyOf", "allOf", "oneOf", "not"}
ANNOTATIONS = {"$schema", "$id", "$defs", "title", "description", "default", "examples", "$comment"}


class SchemaInconnu(LookupError):
    pass


@lru_cache(maxsize=1)
def schemas() -> dict:
    """{$id: schéma} pour tous les fichiers du dossier schemas/."""
    res = {}
    for f in sorted(SCHEMAS.glob("*.schema.json")):
        s = json.loads(f.read_text(encoding="utf-8"))
        res[s["$id"]] = s
    return res


def _base() -> str:
    return next(iter(schemas())).rsplit("/", 1)[0] + "/"


def uri_cible(cible: str) -> str:
    nom, _, defn = cible.partition("#")
    uri = f"{_base()}{nom}.schema.json"
    if uri not in schemas():
        raise SchemaInconnu(f"Schéma inconnu : {nom} (voir --liste)")
    if defn:
        if defn not in schemas()[uri].get("$defs", {}):
            raise SchemaInconnu(f"Définition inconnue : {cible}")
        return f"{uri}#/$defs/{defn}"
    return uri


def cibles() -> list[str]:
    res = []
    for uri, s in schemas().items():
        nom = uri.rsplit("/", 1)[1].removesuffix(".schema.json")
        if nom != "commun":
            res.append(nom)
        res += [f"{nom}#{d}" for d in s.get("$defs", {})]
    return res


# ------------------------------------------------------------------------- moteur interne
def _pointeur(doc, fragment: str):
    if fragment in ("", "/"):
        return doc
    for morceau in fragment.lstrip("/").split("/"):
        morceau = morceau.replace("~1", "/").replace("~0", "~")
        doc = doc[int(morceau)] if isinstance(doc, list) else doc[morceau]
    return doc


def _resoudre(ref: str, base: str):
    absolu = urljoin(base, ref)
    uri, fragment = urldefrag(absolu)
    if uri not in schemas():
        raise SchemaInconnu(f"$ref introuvable : {ref} (base {base})")
    return _pointeur(schemas()[uri], fragment), uri


def _type_ok(v, t: str) -> bool:
    if t == "null":
        return v is None
    if t == "boolean":
        return isinstance(v, bool)
    if t == "integer":
        return not isinstance(v, bool) and (isinstance(v, int) or (isinstance(v, float) and v.is_integer()))
    if t == "number":
        return not isinstance(v, bool) and isinstance(v, (int, float)) and not (isinstance(v, float) and math.isnan(v))
    return isinstance(v, {"string": str, "array": list, "object": dict}[t])


def _egal(a, b) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    return a == b


def _erreurs(v, s, base: str, chemin: str) -> list[str]:
    if s is True or s == {}:
        return []
    if s is False:
        return [f"{chemin or '/'} : aucune valeur permise"]
    if "$id" in s:
        base = s["$id"]
    err: list[str] = []
    ici = chemin or "/"
    if "$ref" in s:
        cible, b2 = _resoudre(s["$ref"], base)
        err += _erreurs(v, cible, b2, chemin)
    if "type" in s:
        types = s["type"] if isinstance(s["type"], list) else [s["type"]]
        if not any(_type_ok(v, t) for t in types):
            return err + [f"{ici} : type attendu {'|'.join(types)}, reçu {type(v).__name__}"]
    if "enum" in s and not any(_egal(v, e) for e in s["enum"]):
        err.append(f"{ici} : valeur {v!r} hors de {s['enum']}")
    if "const" in s and not _egal(v, s["const"]):
        err.append(f"{ici} : valeur {v!r} différente de {s['const']!r}")
    if isinstance(v, str):
        if len(v) < s.get("minLength", 0):
            err.append(f"{ici} : texte trop court (min {s['minLength']})")
        if "maxLength" in s and len(v) > s["maxLength"]:
            err.append(f"{ici} : texte trop long (max {s['maxLength']})")
        if "pattern" in s and not re.search(s["pattern"], v):
            err.append(f"{ici} : {v[:60]!r} ne respecte pas le motif {s['pattern']}")
    if _type_ok(v, "number"):
        if "minimum" in s and v < s["minimum"]:
            err.append(f"{ici} : {v} < minimum {s['minimum']}")
        if "maximum" in s and v > s["maximum"]:
            err.append(f"{ici} : {v} > maximum {s['maximum']}")
        if "exclusiveMinimum" in s and v <= s["exclusiveMinimum"]:
            err.append(f"{ici} : {v} ≤ {s['exclusiveMinimum']}")
    if isinstance(v, list):
        if len(v) < s.get("minItems", 0):
            err.append(f"{ici} : moins de {s['minItems']} élément(s)")
        if "maxItems" in s and len(v) > s["maxItems"]:
            err.append(f"{ici} : plus de {s['maxItems']} éléments")
        if "items" in s:
            for i, x in enumerate(v):
                err += _erreurs(x, s["items"], base, f"{chemin}/{i}")
    if isinstance(v, dict):
        props = s.get("properties", {})
        for cle in s.get("required", []):
            if cle not in v:
                err.append(f"{ici} : champ obligatoire absent « {cle} »")
        for cle, x in v.items():
            if cle in props:
                err += _erreurs(x, props[cle], base, f"{chemin}/{cle}")
            elif "additionalProperties" in s:
                ap = s["additionalProperties"]
                if ap is False:
                    err.append(f"{ici} : champ non permis « {cle} »")
                else:
                    err += _erreurs(x, ap, base, f"{chemin}/{cle}")
    for sous in s.get("allOf", []):
        err += _erreurs(v, sous, base, chemin)
    if "anyOf" in s and not any(not _erreurs(v, x, base, chemin) for x in s["anyOf"]):
        err.append(f"{ici} : aucune alternative (anyOf) ne convient")
    if "oneOf" in s and sum(not _erreurs(v, x, base, chemin) for x in s["oneOf"]) != 1:
        err.append(f"{ici} : il faut exactement une alternative (oneOf)")
    if "not" in s and not _erreurs(v, s["not"], base, chemin):
        err.append(f"{ici} : valeur interdite (not)")
    return err


def _valider_interne(instance, uri: str) -> list[str]:
    s, base = _resoudre(uri, uri)
    return _erreurs(instance, s, base, "")


# ------------------------------------------------------------------------- moteur jsonschema
def jsonschema_disponible() -> bool:
    try:
        import jsonschema  # noqa: F401
        import referencing  # noqa: F401
        return True
    except ImportError:
        return False


@lru_cache(maxsize=1)
def _registre():
    from referencing import Registry, Resource
    return Registry().with_resources((u, Resource.from_contents(s)) for u, s in schemas().items())


def _valider_jsonschema(instance, uri: str) -> list[str]:
    from jsonschema import Draft202012Validator
    v = Draft202012Validator({"$ref": uri}, registry=_registre())
    return [f"/{'/'.join(map(str, e.absolute_path))} : {e.message}"
            for e in sorted(v.iter_errors(instance), key=lambda e: list(map(str, e.absolute_path)))]


# ------------------------------------------------------------------------- API publique
def valider(instance, cible: str, moteur: str = "auto") -> list[str]:
    """Liste des erreurs (vide si l'objet est conforme)."""
    uri = uri_cible(cible)
    if moteur == "auto":
        moteur = "jsonschema" if jsonschema_disponible() else "interne"
    if moteur == "jsonschema":
        return _valider_jsonschema(instance, uri)
    if moteur == "interne":
        return _valider_interne(instance, uri)
    raise ValueError(f"moteur inconnu : {moteur}")


def livrable_depuis_mission(m: dict) -> dict:
    """Vue « Livrable » (livrable.schema.json) d'une mission renvoyée par GET /api/missions/{id}."""
    d = {"mission_id": m["id"], "projet": m.get("projet") or "divers", "service": m.get("service"),
         "niveau": m.get("niveau"), "statut": m["statut"], "texte": m.get("livrable_texte"),
         "valide_par_humain": m["statut"] == "validee"}
    for cle in ("fonctionnement", "tokens", "cout_eur", "duree_s"):
        if m.get(cle) is not None:
            d[cle] = m[cle]
    return d


def verifier_schemas() -> list[str]:
    """Contrôle les schémas : $ref résolubles, mots-clés connus du moteur interne, méta-schéma si possible."""
    pb = []

    def parcourir(s, base, chemin):
        if isinstance(s, list):
            for i, x in enumerate(s):
                parcourir(x, base, f"{chemin}/{i}")
            return
        if not isinstance(s, dict):
            return
        base = s.get("$id", base)
        for cle, x in s.items():
            if cle.startswith("x-") or cle in ANNOTATIONS | APPLIQUES:
                pass
            else:
                pb.append(f"{chemin} : mot-clé non pris en charge par le moteur interne « {cle} »")
            if cle == "$ref":
                try:
                    _resoudre(x, base)
                except (SchemaInconnu, KeyError, IndexError) as e:
                    pb.append(f"{chemin} : {e}")
            elif cle in ("properties", "$defs"):
                for k, sous in x.items():
                    parcourir(sous, base, f"{chemin}/{cle}/{k}")
            elif cle in ("items", "additionalProperties", "not") or cle in ("anyOf", "allOf", "oneOf"):
                parcourir(x, base, f"{chemin}/{cle}")

    for uri, s in schemas().items():
        if s.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            pb.append(f"{uri} : $schema doit être draft 2020-12")
        parcourir(s, uri, uri.rsplit("/", 1)[1])
        if jsonschema_disponible():
            from jsonschema import Draft202012Validator
            from jsonschema.exceptions import SchemaError
            try:
                Draft202012Validator.check_schema(s)
            except SchemaError as e:
                pb.append(f"{uri} : méta-schéma : {e.message}")
    return pb


def _agents(dossier: Path, moteur: str) -> int:
    try:
        import yaml
    except ImportError:
        print("PyYAML est requis pour --agents (pip install pyyaml).", file=sys.stderr)
        return 2
    fichiers = sorted(dossier.glob("*.yaml"))
    ko = 0
    for f in fichiers:
        e = valider(yaml.safe_load(f.read_text(encoding="utf-8")) or {}, "agent", moteur)
        if e:
            ko += 1
            print(f"KO {f.name}\n  " + "\n  ".join(e[:5]))
    print(f"{len(fichiers) - ko}/{len(fichiers)} fiche(s) agent conforme(s) au protocole {VERSION}.")
    return 1 if ko or not fichiers else 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=f"Validation Protocole NEXUS {VERSION}")
    p.add_argument("cible", nargs="?")
    p.add_argument("fichiers", nargs="*")
    p.add_argument("--moteur", default="auto", choices=["auto", "interne", "jsonschema"])
    p.add_argument("--agents", type=Path)
    p.add_argument("--verifier-schemas", action="store_true")
    p.add_argument("--liste", action="store_true")
    a = p.parse_args(argv)
    if a.moteur == "jsonschema" and not jsonschema_disponible():
        print("jsonschema n'est pas installé : utilisez --moteur interne.", file=sys.stderr)
        return 2
    if a.liste:
        print("\n".join(cibles()))
        return 0
    if a.verifier_schemas:
        pb = verifier_schemas()
        print("\n".join(pb) if pb else f"{len(schemas())} schéma(s) cohérent(s) — protocole {VERSION}.")
        return 1 if pb else 0
    if a.agents:
        return _agents(a.agents, a.moteur)
    if not a.cible or not a.fichiers:
        p.error("indiquez une cible et au moins un fichier JSON (ou --agents / --verifier-schemas / --liste)")
    code = 0
    for f in a.fichiers:
        try:
            e = valider(json.loads(Path(f).read_text(encoding="utf-8")), a.cible, a.moteur)
        except (SchemaInconnu, json.JSONDecodeError) as ex:
            print(f"ERREUR {f} : {ex}")
            return 2
        print(f"{'OK' if not e else 'KO'} {f}" + "".join(f"\n  {x}" for x in e[:20]))
        code = code or (1 if e else 0)
    return code


if __name__ == "__main__":
    sys.exit(main())

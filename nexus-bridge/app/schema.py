"""Validation minimale des arguments d'outils selon leur schéma JSON (sous-ensemble utilisé ici).

Pris en charge : type (object, string, integer, boolean, array), properties, required,
additionalProperties=false, enum, minLength, maxLength, minimum, maximum, items, maxItems,
pattern. Les messages d'erreur sont en français.
"""
import re


class ErreurArguments(ValueError):
    pass


_TYPES = {"string": str, "boolean": bool, "array": list, "object": dict}


def _verifier(valeur, schema: dict, chemin: str) -> None:
    t = schema.get("type")
    if t == "integer":
        # bool est un sous-type d'int en Python : on l'exclut explicitement.
        if isinstance(valeur, bool) or not isinstance(valeur, int):
            if isinstance(valeur, float) and valeur.is_integer():
                valeur = int(valeur)
            else:
                raise ErreurArguments(f"« {chemin} » doit être un nombre entier.")
        if "minimum" in schema and valeur < schema["minimum"]:
            raise ErreurArguments(f"« {chemin} » doit être ≥ {schema['minimum']}.")
        if "maximum" in schema and valeur > schema["maximum"]:
            raise ErreurArguments(f"« {chemin} » doit être ≤ {schema['maximum']}.")
    elif t in _TYPES:
        if not isinstance(valeur, _TYPES[t]) or (t != "boolean" and isinstance(valeur, bool)):
            noms = {"string": "un texte", "boolean": "vrai ou faux", "array": "une liste", "object": "un objet"}
            raise ErreurArguments(f"« {chemin} » doit être {noms[t]}.")
    if "enum" in schema and valeur not in schema["enum"]:
        raise ErreurArguments(f"« {chemin} » doit valoir l'une de ces valeurs : {', '.join(map(str, schema['enum']))}.")
    if t == "string":
        if len(valeur) < schema.get("minLength", 0):
            raise ErreurArguments(f"« {chemin} » ne doit pas être vide.")
        if "maxLength" in schema and len(valeur) > schema["maxLength"]:
            raise ErreurArguments(f"« {chemin} » dépasse {schema['maxLength']} caractères.")
        if "pattern" in schema and not re.search(schema["pattern"], valeur):
            raise ErreurArguments(f"« {chemin} » n'a pas le bon format.")
    elif t == "array":
        if "maxItems" in schema and len(valeur) > schema["maxItems"]:
            raise ErreurArguments(f"« {chemin} » contient plus de {schema['maxItems']} éléments.")
        for i, v in enumerate(valeur):
            _verifier(v, schema.get("items", {}), f"{chemin}[{i}]")
    elif t == "object":
        props = schema.get("properties", {})
        for cle in schema.get("required", []):
            if cle not in valeur or valeur[cle] is None:
                raise ErreurArguments(f"Paramètre obligatoire manquant : « {cle} ».")
        if schema.get("additionalProperties") is False:
            inconnus = [k for k in valeur if k not in props]
            if inconnus:
                raise ErreurArguments(f"Paramètre inconnu : « {inconnus[0]} ». Paramètres possibles : {', '.join(props) or 'aucun'}.")
        for cle, v in valeur.items():
            if cle in props and v is not None:
                _verifier(v, props[cle], cle if chemin == "" else f"{chemin}.{cle}")


def valider(arguments, schema: dict) -> dict:
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise ErreurArguments("Les arguments doivent être un objet JSON.")
    _verifier(arguments, schema, "")
    # Valeurs par défaut déclarées dans le schéma
    resultat = dict(arguments)
    for cle, sch in schema.get("properties", {}).items():
        if resultat.get(cle) is None and "default" in sch:
            resultat[cle] = sch["default"]
        if sch.get("type") == "integer" and isinstance(resultat.get(cle), float):
            resultat[cle] = int(resultat[cle])
    return resultat

#!/usr/bin/env bash
# =============================================================================
#  bridge-connecteurs.sh — affiche, pour chaque IA, l'adresse MCP à copier
#  pour la relier à la passerelle nexus-bridge (mémoire commune) du Mothership.
#
#  ATTENTION : chaque adresse CONTIENT le jeton secret de l'IA. Ne la collez
#  que dans les paramètres de l'IA concernée ; ne la partagez jamais.
#
#  Usage :  bash bridge-connecteurs.sh            (les 3 IA)
#           bash bridge-connecteurs.sh claude     (une seule : claude | chatgpt | gemini)
#           bash bridge-connecteurs.sh proprietaire  (votre jeton personnel)
#  Changer un jeton : supprimez sa ligne BRIDGE_TOKEN_... dans .env,
#  relancez « bash install.sh », puis recollez la nouvelle adresse dans l'IA.
# =============================================================================
set -euo pipefail
KIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$KIT_DIR/.env"

titre() { printf '\n\033[1;36m━━ %s\033[0m\n' "$*"; }
avert() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
erreur(){ printf '\033[1;31m[ERREUR]\033[0m %s\n' "$*" >&2; exit 1; }

case "${1:-tous}" in
  -h|--help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  tous|claude|chatgpt|gemini|proprietaire) CHOIX="${1:-tous}" ;;
  *) erreur "Choix inconnu : « $1 » (claude, chatgpt, gemini ou proprietaire)" ;;
esac

[ -r "$ENV_FILE" ] || erreur "$ENV_FILE illisible : lancez ce script en root sur le VPS, après install.sh."

# Lit une variable du .env (retire les apostrophes éventuelles)
lire_env() {
  { grep -E "^${1}=" "$ENV_FILE" || true; } | tail -n 1 | cut -d= -f2- | sed "s/^'//; s/'\$//"
}

HOTE="$(lire_env NEXUS_HOST)"
HOTE="${HOTE:-srvXXXX.hstgr.cloud}"

url_de() {
  local ia="$1" jeton
  jeton="$(lire_env "BRIDGE_TOKEN_$(printf '%s' "$ia" | tr '[:lower:]' '[:upper:]')")"
  if [ "${#jeton}" -lt 32 ]; then
    echo ""
    return 0
  fi
  printf 'https://%s/mcp/%s' "$HOTE" "$jeton"
}

afficher_url() {
  local ia="$1" url
  url="$(url_de "$ia")"
  if [ -z "$url" ]; then
    avert "Pas de jeton BRIDGE_TOKEN_${ia^^} valide dans .env : relancez « bash install.sh »."
    return 1
  fi
  printf '  Adresse à copier (secrète) :\n\n      \033[1m%s\033[0m\n\n' "$url"
}

echo "Passerelle NEXUS — connecteurs MCP pour $HOTE"
echo "Les menus des applications changent souvent : si un intitulé diffère, cherchez"
echo "« Connecteurs », « Applications » ou « MCP » dans les paramètres."

if [ "$CHOIX" = "tous" ] || [ "$CHOIX" = "claude" ]; then
  titre "CLAUDE (claude.ai, sur le web ou l'application de bureau)"
  afficher_url claude || true
  cat <<'EOF'
  1. Ouvrez claude.ai dans un navigateur (l'ajout se fait sur le web ou l'appli
     de bureau ; ensuite le connecteur marche aussi dans l'appli Android).
  2. Paramètres > Connecteurs (parfois « Personnaliser > Connecteurs ») >
     « Ajouter un connecteur personnalisé ».
  3. Nom : NEXUS Passerelle — URL : collez l'adresse ci-dessus.
     Authentification : aucune (le jeton est déjà dans l'adresse). Ajouter.
  4. Dans une conversation : bouton « + » > Connecteurs > activez « NEXUS Passerelle ».
  Offres : Gratuit limité à 1 connecteur personnalisé ; Team/Enterprise : seul un
  administrateur peut l'ajouter pour l'organisation.
EOF
fi

if [ "$CHOIX" = "tous" ] || [ "$CHOIX" = "chatgpt" ]; then
  titre "CHATGPT (chatgpt.com, sur le web)"
  afficher_url chatgpt || true
  cat <<'EOF'
  1. Ouvrez chatgpt.com dans un navigateur (pas l'appli mobile).
  2. Paramètres > Applications (anciennement « Connecteurs ») > Paramètres avancés
     > activez le « Mode développeur ».
  3. Toujours dans Applications : « Créer une application » (ou « Ajouter un
     serveur MCP »). Nom : NEXUS Passerelle — URL du serveur MCP : collez l'adresse.
     Authentification : « Aucune ». Cochez la case de confiance si elle est demandée.
  4. Dans une conversation : bouton « + » > choisissez l'application NEXUS Passerelle
     (sous « Mode développeur » ou « Plus »). ChatGPT demande de confirmer chaque
     écriture : c'est normal.
  Offres : mode développeur réservé aux offres payantes (Plus, Pro, Business,
  Enterprise, Edu) ; pas disponible en offre gratuite.
EOF
fi

if [ "$CHOIX" = "tous" ] || [ "$CHOIX" = "gemini" ]; then
  titre "GEMINI"
  url_g="$(url_de gemini)"
  afficher_url gemini || true
  cat <<EOF
  a) Gemini CLI (ordinateur ; ou Termux sur Android) — fichier ~/.gemini/settings.json :

      {
        "mcpServers": {
          "nexus": {
            "httpUrl": "${url_g:-https://$HOTE/mcp/VOTRE_JETON_GEMINI}",
            "timeout": 30000
          }
        }
      }

     (s'il existe déjà une clé « mcpServers », ajoutez seulement le bloc « nexus »).
     Puis lancez « gemini » et tapez /mcp : « nexus » doit apparaître avec ses outils.
     Variante sans jeton dans l'adresse : "httpUrl": "https://$HOTE/mcp" et
     "headers": { "Authorization": "Bearer <jeton>" }.

  b) Application Gemini (téléphone / gemini.google.com) : elle ne permet pas encore
     d'ajouter un serveur MCP personnel. Continuez avec la méthode miroir Google Doc
     déjà en place : Claude ou ChatGPT recopient la passation et les tâches de la
     passerelle dans le Google Doc miroir, que Gemini lit ; ce que Gemini y note est
     reporté dans la passerelle par Claude ou ChatGPT lors de leur session suivante.
EOF
fi

if [ "$CHOIX" = "proprietaire" ]; then
  titre "VOTRE JETON PERSONNEL (propriétaire)"
  afficher_url proprietaire || true
  echo "  Réservé à vous (ex. un client MCP personnel) : il permet d'archiver n'importe"
  echo "  quelle mémoire et de valider les tâches « a_valider ». Ne le donnez à aucune IA."
fi

cat <<EOF

━━ Suivi (lecture seule) : https://$HOTE/bridge   (identifiants du cockpit)
   Premier essai, dans chaque IA : « Utilise la passerelle NEXUS : lis tes messages,
   puis écris en mémoire que la passerelle fonctionne pour toi. »
EOF

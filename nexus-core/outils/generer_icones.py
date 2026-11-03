"""Génère les icônes du cockpit (SVG + PNG) à partir d'un même dessin.

Outil de développement (PIL requis sur le poste) : les fichiers produits sont versionnés dans
app/static/icones/ ; l'image Docker n'a pas besoin de PIL.
    python3 outils/generer_icones.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

DOSSIER = Path(__file__).resolve().parent.parent / "app" / "static" / "icones"
FOND, TRAIT, ACCENT = (11, 79, 214), (255, 255, 255), (255, 196, 61)

# Dessin sur une grille 100 × 100 : carré arrondi bleu, « N » blanc, point doré (décision).
N_POINTS = [(28, 74), (28, 26), (72, 74), (72, 26)]
SVG = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <rect width="100" height="100" rx="22" fill="rgb{FOND}"/>
  <polyline points="{' '.join(f'{x},{y}' for x, y in N_POINTS)}" fill="none" stroke="rgb{TRAIT}"
            stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="80" cy="80" r="8" fill="rgb{ACCENT}"/>
</svg>
"""


def png(taille: int, marge_securite: bool = False) -> Image.Image:
    f = 4  # suréchantillonnage pour l'anticrénelage
    t = taille * f
    img = Image.new("RGBA", (t, t), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if marge_securite:  # icône « maskable » : fond plein, dessin réduit dans la zone sûre (80 %)
        d.rectangle([0, 0, t, t], fill=FOND)
        echelle, decalage = 0.8 * t / 100, 0.1 * t
    else:
        d.rounded_rectangle([0, 0, t - 1, t - 1], radius=int(0.22 * t), fill=FOND)
        echelle, decalage = t / 100, 0
    p = [(decalage + x * echelle, decalage + y * echelle) for x, y in N_POINTS]
    largeur = int(10 * echelle)
    d.line(p, fill=TRAIT, width=largeur, joint="curve")
    for x, y in p:
        r = largeur / 2
        d.ellipse([x - r, y - r, x + r, y + r], fill=TRAIT)
    cx, cy, r = decalage + 80 * echelle, decalage + 80 * echelle, 8 * echelle
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=ACCENT)
    return img.resize((taille, taille), Image.LANCZOS)


def main() -> None:
    DOSSIER.mkdir(parents=True, exist_ok=True)
    (DOSSIER / "icone.svg").write_text(SVG, encoding="utf-8")
    for taille in (192, 512):
        png(taille).save(DOSSIER / f"icone-{taille}.png", optimize=True)
    png(512, marge_securite=True).save(DOSSIER / "icone-maskable-512.png", optimize=True)
    png(180, marge_securite=True).convert("RGB").save(DOSSIER / "apple-touch-icon.png", optimize=True)
    print("Icônes écrites dans", DOSSIER)


if __name__ == "__main__":
    main()

"""
LE 20H VÉLO — Script principal
Collecte l'actu cyclisme WorldTour, génère un post Instagram
via Claude et publie automatiquement via Meta Graph API.

Dépendances : pip install requests feedparser beautifulsoup4 anthropic pillow
Variables d'environnement requises :
  - ANTHROPIC_API_KEY
  - INSTAGRAM_ACCESS_TOKEN
  - INSTAGRAM_ACCOUNT_ID
"""

import os
import json
import datetime
import time
import requests
import feedparser
from bs4 import BeautifulSoup
import anthropic
from PIL import Image, ImageDraw, ImageFont


# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

ANTHROPIC_API_KEY      = os.environ.get("ANTHROPIC_API_KEY")
INSTAGRAM_ACCESS_TOKEN = os.environ.get("INSTAGRAM_ACCESS_TOKEN")
INSTAGRAM_ACCOUNT_ID   = os.environ.get("INSTAGRAM_ACCOUNT_ID")

# Flux RSS à collecter
RSS_SOURCES = [
    {"nom": "Cyclingnews",   "url": "https://www.cyclingnews.com/rss.xml"},
    {"nom": "Cyclism'Actu",  "url": "https://www.cyclismactu.net/feed"},
    {"nom": "VeloNews",      "url": "https://www.velonews.com/feed"},
    {"nom": "Sporza",        "url": "https://sporza.be/nl/categorie/wielrennen.rss.xml"},
    {"nom": "RTBF Sport",    "url": "https://www.rtbf.be/api/dyn?action=get_article_list&cat=sp_cyclisme&output=rss"},
]

# Mots-clés pour filtrer WorldTour et Belges
KEYWORDS_WORLDTOUR = [
    "worldtour", "tour de france", "giro", "vuelta", "paris-roubaix",
    "flandres", "liège", "sanremo", "lombardie", "amstel", "strade",
    "tirreno", "paris-nice", "critérium", "uci", "peloton", "pro cycling"
]
KEYWORDS_BELGES = [
    "evenepoel", "van aert", "van der poel", "wellens", "lampaert",
    "stuyven", "benoot", "de plus", "campenaerts", "dewulf", "belgium",
    "belgique", "belge", "quick-step", "lotto", "intermarché", "soudal"
]


# ─────────────────────────────────────────────
# PROMPT SYSTÈME CLAUDE
# ─────────────────────────────────────────────

SYSTEM_PROMPT = """
Tu es le rédacteur en chef du "20h Vélo", un compte Instagram
de référence sur le cyclisme professionnel WorldTour masculin.

TON RÔLE :
Chaque soir, tu produis un post Instagram carrousel résumant
l'actu cycliste du jour : résultats, transferts et rumeurs du
peloton. Ton ton est décalé, pince-sans-rire, inspiré du
journal télévisé — tu te prends au sérieux pour parler de vélo.
Tu accordes une attention particulière aux coureurs et résultats
belges, sans pour autant ignorer le reste du WorldTour.

TYPE DE POST (indiqué dans les données fournies) :
- "general"     → Résumé de la journée (par défaut)
- "focus"       → Focus sur un sujet fort du jour
- "decouverte"  → Portrait d'un jeune talent ou coureur méconnu
- "classements" → Classements UCI de la semaine

FORMAT DE SORTIE — JSON UNIQUEMENT, rien d'autre :

{
  "type": "general" | "focus" | "decouverte" | "classements",
  "legende": "...",
  "slides": [
    {"numero": 1, "titre": "...", "contenu": "...", "source": "...", "lien": "..."},
    ...
  ],
  "hashtags": "..."
}

RÈGLES POUR LA LÉGENDE (3-5 lignes MAXIMUM) :
- Commence par "Bonsoir et bienvenue au 20h Vélo."
- 1-2 phrases percutantes sur l'actu du jour
- Mentionne en priorité un fait belge si disponible
- Termine par "#le20hvelo"

RÈGLES POUR LES SLIDES — TYPE GÉNÉRAL (5 à 6 slides) :
- Slide 1 : "À LA UNE CE SOIR" — fait le plus marquant du jour
  (belge en priorité si pertinent)
- Slides 2-4 : Résultats / transferts / rumeurs
  (un slide dédié aux Belges si l'actu le permet)
- Slide 5 : "LE CHIFFRE DU JOUR" — une stat marquante
- Slide 6 : "DEMAIN ON PÉDALE" — à suivre le lendemain

RÈGLES POUR LES SLIDES — TYPE FOCUS (3 à 4 slides) :
- Slide 1 : Titre choc sur le sujet du jour
- Slides 2-3 : Développement (contexte, chiffres, enjeux)
- Slide 4 : Analyse ou citation reformulée avec source et lien

RÈGLES POUR LES SLIDES — TYPE DÉCOUVERTE (5 slides) :
- Slide 1 : "LA DÉCOUVERTE DU 20H" — nom et nationalité
- Slide 2 : Portrait rapide (âge, équipe, palmarès)
- Slide 3 : Pourquoi il performe / ce qui le rend spécial
- Slide 4 : Résultats récents avec source et lien
- Slide 5 : "À SUIVRE" — prochaines échéances
- Priorité aux talents belges émergents ou peu médiatisés

RÈGLES POUR LES SLIDES — TYPE CLASSEMENTS (4 slides) :
- Slide 1 : "LES CLASSEMENTS DE LA SEMAINE"
- Slide 2 : Top 10 UCI WorldTour individuel
- Slide 3 : Top 10 UCI WorldTour par équipes
- Slide 4 : Mouvement marquant de la semaine (belge en priorité)
- Uniquement de janvier à octobre

RÈGLES COMMUNES AUX SLIDES :
- Titre court (5 mots max) + contenu (3-4 lignes max)
- Ton JT décalé systématiquement
- Chaque slide cite sa source et son lien quand disponible

CITATION DES SOURCES — RÈGLE ABSOLUE :
- Toute information doit être attribuée à sa source
  Exemples : "selon Cyclingnews", "d'après la VRT",
  "selon Sporza", "d'après L'Équipe"
- Le champ "lien" contient l'URL de l'article source exact
- Si une info n'a pas de source identifiable, elle est ignorée
- Les rumeurs sont clairement identifiées :
  "selon nos confrères de...", "d'après des sources proches de..."

RÈGLE ABSOLUE ANTI-INVENTION :
- Il est STRICTEMENT INTERDIT d'inventer, extrapoler ou supposer
  une information non présente dans les données fournies
- Si les données sont insuffisantes, le post se limite aux infos
  disponibles et le mentionne explicitement
- Aucune citation directe ne peut être inventée sans source

FOCUS BELGE :
- Résultats, transferts et rumeurs belges systématiquement mis
  en avant (Evenepoel, Van Aert, Van der Poel, Quick-Step, etc.)
- Sources belges prioritaires : VRT, RTBF, Sporza, HLN, DH

RÈGLES POUR LES HASHTAGS (6 maximum) :
- Toujours : #le20hvelo #cyclisme #WorldTour
- Hashtags des courses ou coureurs mentionnés
- Si un Belge est à la une : #BelgianCycling

RÈGLES GÉNÉRALES :
- Cyclisme masculin WorldTour uniquement
- Ne jamais reproduire mot pour mot le texte des sources
- Reformuler systématiquement en style JT décalé
- Rester factuel malgré le ton humoristique
"""


# ─────────────────────────────────────────────
# 1. COLLECTE DES FLUX RSS
# ─────────────────────────────────────────────

def collecter_rss():
    """Collecte et filtre les articles RSS du jour."""
    aujourd_hui = datetime.date.today()
    articles = []

    for source in RSS_SOURCES:
        try:
            feed = feedparser.parse(source["url"])
            for entry in feed.entries[:20]:  # max 20 articles par source

                # Filtre : article du jour uniquement
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    date_article = datetime.date(*entry.published_parsed[:3])
                    if date_article < aujourd_hui:
                        continue

                titre   = entry.get("title", "")
                resume  = entry.get("summary", "")
                lien    = entry.get("link", "")
                texte   = (titre + " " + resume).lower()

                # Filtre : WorldTour uniquement
                if not any(kw in texte for kw in KEYWORDS_WORLDTOUR):
                    continue

                # Détection contenu belge
                est_belge = any(kw in texte for kw in KEYWORDS_BELGES)

                articles.append({
                    "source":    source["nom"],
                    "titre":     titre,
                    "resume":    BeautifulSoup(resume, "html.parser").get_text()[:300],
                    "lien":      lien,
                    "est_belge": est_belge,
                })

            time.sleep(1)  # Délai poli entre les requêtes

        except Exception as e:
            print(f"Erreur RSS {source['nom']} : {e}")

    # Belges en premier
    articles.sort(key=lambda x: x["est_belge"], reverse=True)
    print(f"{len(articles)} articles collectés.")
    return articles


# ─────────────────────────────────────────────
# 2. DÉTERMINATION DU TYPE DE POST
# ─────────────────────────────────────────────

def determiner_type_post():
    """Détermine le type de post selon le jour de la semaine."""
    jour = datetime.date.today().weekday()  # 0=lundi, 6=dimanche
    mois = datetime.date.today().month

    if jour == 2:  # Mercredi
        return "decouverte"
    if jour == 6 and 1 <= mois <= 10:  # Dimanche en saison
        return "classements"
    return "general"


# ─────────────────────────────────────────────
# 3. GÉNÉRATION DU POST VIA CLAUDE
# ─────────────────────────────────────────────

def generer_post(articles, type_post):
    """Envoie les données à Claude et récupère le post JSON."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Construction du contexte
    date_str = datetime.date.today().strftime("%d/%m/%Y")
    articles_texte = "\n\n".join([
        f"[{a['source']}] {'(BELGE)' if a['est_belge'] else ''}\n"
        f"Titre : {a['titre']}\n"
        f"Résumé : {a['resume']}\n"
        f"Lien : {a['lien']}"
        for a in articles[:15]  # max 15 articles envoyés
    ])

    user_message = f"""
Date : {date_str}
Type de post demandé : {type_post}

Voici l'actu cyclisme WorldTour du jour :

{articles_texte}

Génère le post du 20h Vélo en JSON uniquement.
"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}]
    )

    texte = response.content[0].text.strip()

    # Nettoyage si Claude ajoute des backticks
    if texte.startswith("```"):
        texte = texte.split("```")[1]
        if texte.startswith("json"):
            texte = texte[4:]

    return json.loads(texte)


# ─────────────────────────────────────────────
# 4. GÉNÉRATION DES IMAGES CARROUSEL
# ─────────────────────────────────────────────

def generer_images(post_json):
    """Génère une image par slide avec Pillow."""
    images = []
    slides = post_json.get("slides", [])

    # Couleurs du 20h Vélo
    COULEUR_FOND    = (15, 15, 20)       # Noir profond
    COULEUR_ACCENT  = (255, 200, 0)      # Jaune vélo
    COULEUR_TEXTE   = (240, 240, 240)    # Blanc cassé
    COULEUR_SECONDAIRE = (160, 160, 170) # Gris clair

    LARGEUR, HAUTEUR = 1080, 1080

    for i, slide in enumerate(slides):
        img  = Image.new("RGB", (LARGEUR, HAUTEUR), COULEUR_FOND)
        draw = ImageDraw.Draw(img)

        # Bande d'accent en haut
        draw.rectangle([0, 0, LARGEUR, 8], fill=COULEUR_ACCENT)

        # Numéro de slide
        draw.text((40, 30), f"{i+1}/{len(slides)}", fill=COULEUR_SECONDAIRE)

        # Logo en haut à droite
        draw.text((LARGEUR - 200, 30), "20h VÉLO", fill=COULEUR_ACCENT)

        # Titre du slide
        titre = slide.get("titre", "").upper()
        draw.text((40, 120), titre, fill=COULEUR_ACCENT)
        draw.line([40, 175, LARGEUR - 40, 175], fill=COULEUR_ACCENT, width=2)

        # Contenu
        contenu = slide.get("contenu", "")
        y = 210
        for ligne in contenu.split("\n"):
            draw.text((40, y), ligne, fill=COULEUR_TEXTE)
            y += 45

        # Source en bas
        source = slide.get("source", "")
        if source:
            draw.text((40, HAUTEUR - 80), f"Source : {source}", fill=COULEUR_SECONDAIRE)

        # Bande d'accent en bas
        draw.rectangle([0, HAUTEUR - 8, LARGEUR, HAUTEUR], fill=COULEUR_ACCENT)

        # Sauvegarde temporaire
        chemin = f"/tmp/slide_{i+1}.jpg"
        img.save(chemin, "JPEG", quality=95)
        images.append(chemin)

    print(f"{len(images)} images générées.")
    return images


# ─────────────────────────────────────────────
# 5. PUBLICATION INSTAGRAM
# ─────────────────────────────────────────────

def publier_instagram(images, legende, hashtags):
    """Publie le carrousel sur Instagram via Meta Graph API."""
    base_url = f"https://graph.facebook.com/v19.0/{INSTAGRAM_ACCOUNT_ID}"
    legende_complete = f"{legende}\n\n{hashtags}"

    # Étape 1 : uploader chaque image
    container_ids = []
    for chemin in images:
        with open(chemin, "rb") as f:
            image_data = f.read()

        # Note : en production, l'image doit être uploadée
        # via une URL publique, pas en local.
        # Utilise un service d'hébergement temporaire (ex: imgbb)
        # ou un bucket S3/Cloudflare R2 gratuit.

        # Exemple avec URL publique :
        # url_image = uploader_image_publique(chemin)
        url_image = "REMPLACE_PAR_URL_PUBLIQUE"

        resp = requests.post(
            f"{base_url}/media",
            data={
                "image_url":    url_image,
                "is_carousel_item": True,
                "access_token": INSTAGRAM_ACCESS_TOKEN,
            }
        )
        container_ids.append(resp.json()["id"])

    # Étape 2 : créer le carrousel
    resp = requests.post(
        f"{base_url}/media",
        data={
            "media_type":    "CAROUSEL",
            "children":      ",".join(container_ids),
            "caption":       legende_complete,
            "access_token":  INSTAGRAM_ACCESS_TOKEN,
        }
    )
    carousel_id = resp.json()["id"]

    # Étape 3 : publier
    resp = requests.post(
        f"{base_url}/media_publish",
        data={
            "creation_id":  carousel_id,
            "access_token": INSTAGRAM_ACCESS_TOKEN,
        }
    )

    if resp.status_code == 200:
        print(f"Post publié ! ID : {resp.json().get('id')}")
    else:
        print(f"Erreur publication : {resp.text}")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    print("=== 20h Vélo — Démarrage ===")

    # 1. Collecte
    articles = collecter_rss()
    if not articles:
        print("Aucun article trouvé aujourd'hui. Arrêt.")
        return

    # 2. Type de post
    type_post = determiner_type_post()
    print(f"Type de post : {type_post}")

    # 3. Génération Claude
    print("Génération du post via Claude...")
    post_json = generer_post(articles, type_post)
    print(json.dumps(post_json, ensure_ascii=False, indent=2))

    # 4. Images
    print("Génération des images...")
    images = generer_images(post_json)

    # 5. Publication
    print("Publication Instagram...")
    publier_instagram(
        images,
        post_json["legende"],
        post_json["hashtags"]
    )

    print("=== Terminé ===")


if __name__ == "__main__":
    main()

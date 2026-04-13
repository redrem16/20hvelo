"""
LE 20H VELO — Script principal v4.3
Collecte l'actu cyclisme WorldTour, génère un post Instagram
via Gemini et publie automatiquement via Meta Graph API.
"""

import os
import json
import datetime
import time
import base64
import textwrap
import requests
import feedparser
from bs4 import BeautifulSoup
import google.generativeai as genai
from PIL import Image, ImageDraw, ImageFont


# ---------------------------------------------
# CONFIG
# ---------------------------------------------

GEMINI_API_KEY         = os.getenv("GEMINI_API_KEY")
INSTAGRAM_ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN")
INSTAGRAM_ACCOUNT_ID   = os.getenv("INSTAGRAM_ACCOUNT_ID")
GITHUB_TOKEN           = os.getenv("GH_TOKEN")

GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY")
GITHUB_BRANCH     = "main"

RSS_SOURCES = [
    {"nom": "Cyclingnews",  "url": "https://www.cyclingnews.com/rss.xml"},
    {"nom": "Cyclism'Actu", "url": "https://www.cyclismactu.net/feed"},
    {"nom": "VeloNews",     "url": "https://www.velonews.com/feed"},
    {"nom": "Sporza",       "url": "https://sporza.be/nl/categorie/wielrennen.rss.xml"},
    {
        "nom": "RTBF Sport",
        "url": "https://www.rtbf.be/api/dyn?action=get_article_list&cat=sp_cyclisme&output=rss",
    },
]

KEYWORDS_WORLDTOUR = [
    "worldtour", "tour de france", "giro", "vuelta",
    "paris-roubaix", "flandres", "liege", "sanremo",
    "lombardie", "amstel", "strade", "tirreno",
    "paris-nice", "criterium", "uci", "peloton",
    "pro cycling",
]

KEYWORDS_BELGES = [
    "evenepoel", "van aert", "van der poel", "wellens",
    "lampaert", "stuyven", "benoot", "de plus",
    "campenaerts", "dewulf", "belgium", "belgique",
    "belge", "quick-step", "lotto", "intermarch", "soudal",
]


# ---------------------------------------------
# PROMPT SYSTEME GEMINI
# ---------------------------------------------

SYSTEM_PROMPT = textwrap.dedent("""\
Tu es le rédacteur de "LE 20H VELO", compte Instagram francophone
de revue de presse quotidienne sur le cyclisme WorldTour.

═══ RÈGLE ABSOLUE — INTERDICTION D'INVENTER ═══
- Tu ne peux utiliser QUE les informations contenues dans les articles fournis
- AUCUN fait, résultat, classement, citation, statistique ou temps ne peut
  être inventé, déduit, extrapolé ou complété de mémoire
- Si un article dit "Evenepoel a gagné", tu peux écrire qu'il a gagné.
  Si l'article ne mentionne pas le temps, tu ne donnes PAS de temps.
- Si une info est présentée comme rumeur dans la source, utilise
  le conditionnel ("pourrait", "serait", "selon X")
- Chaque fait doit être traçable à un article fourni
- Si tu n'as pas assez d'articles, fais MOINS de slides.
  3 slides fiables valent mieux que 6 slides avec du remplissage inventé.
- En cas de doute sur une info : ne pas l'inclure

QUAND CITER LA SOURCE DANS LE TEXTE :
- Ne PAS citer la source systématiquement sur chaque slide
- Citer la source UNIQUEMENT quand c'est journalistiquement nécessaire :
  • Une exclu ou un scoop : "Selon la RTBF, Evenepoel pourrait…"
  • Une rumeur ou info non confirmée : "D'après Cyclingnews, un transfert…"
  • Des infos contradictoires : "Sporza annonce X, alors que VeloNews parle de Y"
  • Une citation directe d'un coureur ou directeur sportif
- Pour les résultats de course, faits établis et infos factuelles évidentes :
  pas besoin de citer la source dans le texte

TON ET STYLE :
- Décontracté, naturel, entre passionnés de cyclisme
- Jargon vélo bienvenu (peloton, baroud, bidon, musette, flamme rouge…)
- Pas d'adresse directe au lecteur (pas de tu/vous)
- Humour léger si ça vient naturellement, jamais forcé
- Emojis : max 2 dans la légende, ZÉRO dans les slides

STRUCTURE DU CARROUSEL :
- Slide 1 = TOUJOURS une couverture : titre "LE 20H VELO" + date du jour
  (contenu : une phrase d'accroche résumant l'actu du jour)
- Slides suivantes = revue de presse, 1 slide = 1 article différent
- Nombre total de slides (couverture incluse) : 3 minimum, 6 maximum
- Adapter le nombre aux articles disponibles

THÈMES COUVERTS (par priorité) :
- Résultats de courses
- Transferts et rumeurs (toujours au conditionnel si non confirmé)
- Blessures et abandons
- Classements UCI (uniquement si type = "classements")
- Coulisses et insolite

ANGLE BELGE :
- Mentionner coureurs/équipes belges quand l'actu s'y prête
- Ne pas forcer si rien de belge dans les articles du jour

CONTENU PAR SLIDE :
- Titre : max 6 mots, percutant
- Contenu : le fait clé + pourquoi c'est important (max 250 caractères)

JSON UNIQUEMENT — format strict :
{"type":"<general|decouverte|classements>","legende":"<1-2 phrases>","slides":[{"numero":1,"titre":"<max 6 mots>","contenu":"<max 250 car>","source":"<nom>","lien":"<url>"}],"hashtags":["#tag"]}

Les champs "source" et "lien" dans le JSON servent à la traçabilité interne,
ils ne sont PAS affichés sur la slide. Seul le "contenu" apparaît visuellement.

Aucun texte hors du JSON. Pas de markdown. Parsable directement.
""")


# ---------------------------------------------
# 1. CACHE JOURNALIER
# ---------------------------------------------

def verifier_cache(date_str):
    return os.path.exists(f"cache/{date_str}.json")


def sauvegarder_cache(date_str, post_json):
    os.makedirs("cache", exist_ok=True)
    with open(f"cache/{date_str}.json", "w", encoding="utf-8") as f:
        json.dump(post_json, f, ensure_ascii=False, indent=2)


# ---------------------------------------------
# 2. COLLECTE RSS
# ---------------------------------------------

def collecter_rss():
    aujourd_hui = datetime.date.today()
    hier = aujourd_hui - datetime.timedelta(days=1)
    articles = []

    for source in RSS_SOURCES:
        try:
            feed = feedparser.parse(source["url"])
            for entry in feed.entries[:20]:
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    date_article = datetime.date(*entry.published_parsed[:3])
                    if date_article < hier:
                        continue

                texte = (entry.title + " " + entry.get("summary", "")).lower()
                if not any(k in texte for k in KEYWORDS_WORLDTOUR):
                    continue

                articles.append({
                    "source": source["nom"],
                    "titre": entry.title,
                    "resume": BeautifulSoup(
                        entry.get("summary", ""), "html.parser"
                    ).get_text()[:150],
                    "lien": entry.link,
                    "est_belge": any(k in texte for k in KEYWORDS_BELGES),
                })
        except Exception as e:
            print(f"⚠️  Erreur RSS pour {source['nom']}: {e}")
        time.sleep(1)

    articles.sort(key=lambda x: x["est_belge"], reverse=True)
    return articles


# ---------------------------------------------
# 3. TYPE DE POST
# ---------------------------------------------

def determiner_type_post():
    jour = datetime.date.today().weekday()
    mois = datetime.date.today().month
    if jour == 6 and 1 <= mois <= 10:
        return "classements"
    return "general"


# ---------------------------------------------
# 4. GENERATION VIA GEMINI
# ---------------------------------------------

def generer_post(articles, type_post):
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(
        "gemini-3-flash-preview",
        system_instruction=SYSTEM_PROMPT,
    )

    articles_txt = "\n".join([
        f"- [{a['source']}] {a['titre']} | {a['lien']}"
        f"{' (BELGE)' if a['est_belge'] else ''}"
        for a in articles[:8]
    ])

    prompt = (
        f"Type: {type_post} | Date: {datetime.date.today().strftime('%d %B %Y')}\n"
        f"Slides: 3-6\n\n{articles_txt}\n\nJSON:"
    )

    response = None
    for tentative in range(3):
        try:
            response = model.generate_content(prompt)
            break
        except Exception as e:
            print(f"  ❌ Erreur Gemini : {type(e).__name__}: {e}")
            if "quota" in str(e).lower() or "429" in str(e):
                delai = 60 * (tentative + 1)
                print(f"  ⏳ Quota Gemini, attente {delai}s ({tentative + 1}/3)...")
                time.sleep(delai)
            else:
                raise
    else:
        raise RuntimeError("Quota Gemini dépassé après 3 tentatives")

    texte = response.text.strip().replace("```json", "").replace("```", "")
    post = json.loads(texte)

    required = {"type", "legende", "slides", "hashtags"}
    if not required.issubset(post):
        raise ValueError(f"JSON incomplet — clés manquantes : {required - set(post.keys())}")

    for i, slide in enumerate(post["slides"]):
        for key in ("numero", "titre", "contenu", "source", "lien"):
            if key not in slide:
                raise ValueError(f"Champ '{key}' manquant dans la slide {i + 1}")

    nb = len(post["slides"])
    if not (3 <= nb <= 6):
        raise ValueError(f"Nombre de slides invalide : {nb} (attendu 3-6)")

    return post


# ---------------------------------------------
# 5. GENERATION DES IMAGES
# ---------------------------------------------

def generer_images(post):
    os.makedirs("slides", exist_ok=True)
    images = []

    try:
        font_titre = ImageFont.truetype("fonts/Inter-Bold.ttf", 64)
        font_txt   = ImageFont.truetype("fonts/Inter-Regular.ttf", 40)
    except IOError:
        print("⚠️  Polices Inter non trouvées, utilisation de la police par défaut")
        font_titre = font_txt = ImageFont.load_default()

    for i, slide in enumerate(post["slides"]):
        img = Image.new("RGB", (1080, 1080), (15, 15, 20))
        draw = ImageDraw.Draw(img)

        draw.text(
            (40, 120),
            slide["titre"].upper(),
            fill=(255, 200, 0),
            font=font_titre,
        )

        y = 240
        for ligne in slide["contenu"].split("\n"):
            for chunk in textwrap.wrap(ligne, 40):
                draw.text((40, y), chunk, fill=(240, 240, 240), font=font_txt)
                y += 52

        path = f"slides/slide_{i + 1}.jpg"
        img.save(path, "JPEG", quality=95)
        images.append(path)

    return images


# ---------------------------------------------
# 6. UPLOAD DES IMAGES SUR GITHUB (un seul commit)
# ---------------------------------------------

def upload_images_github(image_paths):
    if not GITHUB_REPOSITORY or not GITHUB_TOKEN:
        raise ValueError("GITHUB_REPOSITORY ou GH_TOKEN non défini.")

    token = os.getenv("GH_TOKEN")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    api = f"https://api.github.com/repos/{GITHUB_REPOSITORY}"
    date_str = datetime.date.today().isoformat()

    resp = requests.get(f"{api}/git/ref/heads/{GITHUB_BRANCH}", headers=headers)
    resp.raise_for_status()
    last_commit_sha = resp.json()["object"]["sha"]

    resp = requests.get(f"{api}/git/commits/{last_commit_sha}", headers=headers)
    resp.raise_for_status()
    base_tree_sha = resp.json()["tree"]["sha"]

    tree_items = []
    for img_path in image_paths:
        with open(img_path, "rb") as f:
            contenu_b64 = base64.b64encode(f.read()).decode("utf-8")

        resp = requests.post(
            f"{api}/git/blobs",
            headers=headers,
            json={"content": contenu_b64, "encoding": "base64"},
        )
        resp.raise_for_status()
        blob_sha = resp.json()["sha"]

        filename = os.path.basename(img_path)
        tree_items.append({
            "path": f"images/{date_str}/{filename}",
            "mode": "100644",
            "type": "blob",
            "sha": blob_sha,
        })
        print(f"  📦 Blob créé : {filename}")

    resp = requests.post(
        f"{api}/git/trees",
        headers=headers,
        json={"base_tree": base_tree_sha, "tree": tree_items},
    )
    resp.raise_for_status()
    new_tree_sha = resp.json()["sha"]

    resp = requests.post(
        f"{api}/git/commits",
        headers=headers,
        json={
            "message": f"slides {date_str}",
            "tree": new_tree_sha,
            "parents": [last_commit_sha],
        },
    )
    resp.raise_for_status()
    new_commit_sha = resp.json()["sha"]

    resp = requests.patch(
        f"{api}/git/refs/heads/{GITHUB_BRANCH}",
        headers=headers,
        json={"sha": new_commit_sha},
    )
    resp.raise_for_status()
    print(f"  ✅ Commit créé avec {len(image_paths)} images")

    urls = []
    for img_path in image_paths:
        filename = os.path.basename(img_path)
        raw_url = (
            f"https://raw.githubusercontent.com/{GITHUB_REPOSITORY}"
            f"/{GITHUB_BRANCH}/images/{date_str}/{filename}"
        )
        urls.append(raw_url)

    return urls


# ---------------------------------------------
# 7. PUBLICATION INSTAGRAM (carrousel)
# ---------------------------------------------

def publier_instagram(post, images):
    base_url = "https://graph.facebook.com/v25.0"

    # Debug : vérifier les variables
    print(f"  🔍 DEBUG INSTAGRAM_ACCOUNT_ID = [{INSTAGRAM_ACCOUNT_ID}]")
    print(f"  🔍 DEBUG TOKEN length = {len(INSTAGRAM_ACCESS_TOKEN) if INSTAGRAM_ACCESS_TOKEN else 0}")

    # Upload toutes les images en un seul commit
    print("  📤 Upload des images sur GitHub...")
    image_urls = upload_images_github(images)

    print("  ⏳ Attente propagation GitHub (15s)...")
    time.sleep(15)

    # Créer les containers Instagram
    print("  📦 Création des containers Instagram...")
    container_ids = []

    for image_url in image_urls:
        url = f"{base_url}/{INSTAGRAM_ACCOUNT_ID}/media"
        print(f"  🔍 POST → {url}")
        print(f"  🔍 image_url → {image_url}")

        resp = requests.post(
            url,
            data={
                "image_url": image_url,
                "is_carousel_item": "true",
                "access_token": INSTAGRAM_ACCESS_TOKEN,
            },
        )
        print(f"  🔍 Meta container : {resp.status_code} — {resp.text}")
        resp.raise_for_status()
        container_ids.append(resp.json()["id"])
        print(f"  📦 Container : {resp.json()['id']}")

    # Créer le carrousel
    print("  🎠 Création du carrousel...")
    legende = post["legende"] + "\n\n" + " ".join(post["hashtags"])

    resp = requests.post(
        f"{base_url}/{INSTAGRAM_ACCOUNT_ID}/media",
        data={
            "media_type": "CAROUSEL",
            "children": ",".join(container_ids),
            "caption": legende,
            "access_token": INSTAGRAM_ACCESS_TOKEN,
        },
    )
    print(f"  🔍 Meta carrousel : {resp.status_code} — {resp.text}")
    resp.raise_for_status()
    carousel_id = resp.json()["id"]

    # Publier
    print("  ⏳ Attente traitement Meta (30s)...")
    time.sleep(30)

    resp = requests.post(
        f"{base_url}/{INSTAGRAM_ACCOUNT_ID}/media_publish",
        data={
            "creation_id": carousel_id,
            "access_token": INSTAGRAM_ACCESS_TOKEN,
        },
    )
    print(f"  🔍 Meta publish : {resp.status_code} — {resp.text}")
    resp.raise_for_status()
    post_id = resp.json()["id"]
    print(f"  ✅ Publié sur Instagram ! Post ID : {post_id}")

    return post_id


# ---------------------------------------------
# 8. MAIN
# ---------------------------------------------

def main():
    print("=" * 50)
    print("LE 20H VELO — Publication automatique")
    print("=" * 50)

    date_str = datetime.date.today().isoformat()

    if verifier_cache(date_str):
        print(f"⏭️  Post déjà généré pour {date_str}, on skip.")
        return

    print("\n📡 Collecte des articles RSS...")
    articles = collecter_rss()

    if not articles:
        print("⚠️  Aucun article WorldTour trouvé aujourd'hui. Abandon.")
        return

    print(f"📰 {len(articles)} articles trouvés")
    belges = sum(1 for a in articles if a["est_belge"])
    if belges:
        print(f"   dont {belges} article(s) belge(s)")

    type_post = determiner_type_post()
    print(f"\n📝 Type de post du jour : {type_post}")

    print("\n🤖 Génération du contenu via Gemini...")
    post = generer_post(articles, type_post)
    print(f"   {len(post['slides'])} slides générées")

    print("\n🎨 Génération des images...")
    images = generer_images(post)
    print(f"   {len(images)} images créées")

    print("\n📤 Publication sur Instagram...")
    publier_instagram(post, images)

    sauvegarder_cache(date_str, post)

    print("\n" + "=" * 50)
    print("✅ LE 20H VELO — Terminé avec succès !")
    print("=" * 50)


if __name__ == "__main__":
    main()

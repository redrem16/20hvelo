"""
LE 20H VELO — Script principal FINAL v3.1
Collecte l'actu cyclisme WorldTour, genere un post Instagram
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
GITHUB_USERNAME        = os.getenv("GITHUB_USERNAME")
GITHUB_REPO            = "le20hvelo"
GITHUB_BRANCH          = "main"

SLIDES_ATTENDUS = {
    "general":     (5, 6),
    "focus":       (3, 4),
    "decouverte":  (5, 5),
    "classements": (4, 4),
}

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
    "pro cycling"
]

KEYWORDS_BELGES = [
    "evenepoel", "van aert", "van der poel", "wellens",
    "lampaert", "stuyven", "benoot", "de plus",
    "campenaerts", "dewulf", "belgium", "belgique",
    "belge", "quick-step", "lotto", "intermarch", "soudal"
]


# ---------------------------------------------
# PROMPT SYSTEME GEMINI
# ---------------------------------------------

SYSTEM_PROMPT = """[PROMPT IDENTIQUE A v3 — INCHANGE]
(aucune modification necessaire ici)
"""


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
    articles = []

    for source in RSS_SOURCES:
        feed = feedparser.parse(source["url"])
        for entry in feed.entries[:20]:

            if hasattr(entry, "published_parsed") and entry.published_parsed:
                date_article = datetime.date(*entry.published_parsed[:3])
                if date_article < aujourd_hui:
                    continue

            texte = (entry.title + " " + entry.get("summary", "")).lower()
            if not any(k in texte for k in KEYWORDS_WORLDTOUR):
                continue

            articles.append({
                "source": source["nom"],
                "titre": entry.title,
                "resume": BeautifulSoup(entry.get("summary",""), "html.parser").get_text()[:300],
                "lien": entry.link,
                "est_belge": any(k in texte for k in KEYWORDS_BELGES)
            })

        time.sleep(1)

    articles.sort(key=lambda x: x["est_belge"], reverse=True)
    return articles


# ---------------------------------------------
# 3. TYPE DE POST
# ---------------------------------------------

def determiner_type_post():
    jour = datetime.date.today().weekday()
    mois = datetime.date.today().month

    if jour == 2:
        return "decouverte"
    if jour == 6 and 1 <= mois <= 10:
        return "classements"
    return "general"


# ---------------------------------------------
# 4. GENERATION VIA GEMINI
# ---------------------------------------------

def generer_post(articles, type_post):
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(
        "gemini-1.5-flash",
        system_instruction=SYSTEM_PROMPT
    )

    articles_txt = "\n\n".join([
        f"[{a['source']}]{' (BELGE - PRIORITE)' if a['est_belge'] else ''}\n"
        f"Titre : {a['titre']}\nResume : {a['resume']}\nLien : {a['lien']}"
        for a in articles[:15]
    ])

    min_s, max_s = SLIDES_ATTENDUS[type_post]

    prompt = f"""
Type de post : {type_post}
Nombre de slides requis : {min_s}-{max_s}

Articles :
{articles_txt}

Genere UNIQUEMENT le JSON final.
"""

    response = model.generate_content(prompt)
    texte = response.text.strip().replace("```json", "").replace("```", "")

    post = json.loads(texte)

    # Validation structurelle
    required = {"type", "legende", "slides", "hashtags"}
    if not required.issubset(post):
        raise ValueError("JSON incomplet retourne par Gemini")

    for slide in post["slides"]:
        for key in ("numero", "titre", "contenu", "source", "lien"):
            if key not in slide:
                raise ValueError("Champ manquant dans une slide")

    if not (min_s <= len(post["slides"]) <= max_s):
        raise ValueError("Nombre de slides invalide")

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
        font_small = ImageFont.truetype("fonts/Inter-Regular.ttf", 28)
    except IOError:
        font_titre = font_txt = font_small = ImageFont.load_default()

    for i, slide in enumerate(post["slides"]):
        img = Image.new("RGB", (1080,1080), (15,15,20))
        draw = ImageDraw.Draw(img)

        draw.text((40,120), slide["titre"].upper(), fill=(255,200,0), font=font_titre)

        y = 240
        for ligne in slide["contenu"].split("\n"):
            for chunk in textwrap.wrap(ligne, 40):
                draw.text((40,y), chunk, fill=(240,240,240), font=font_txt)
                y += 52

        path = f"slides/slide_{i+1}.jpg"
        img.save(path, "JPEG", quality=95)
        images.append(path)

    return images


# ---------------------------------------------
# 6. GITHUB UPLOAD
# ---------------------------------------------

def uploader_images(images):
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    urls = []
    for path in images:
        name = os.path.basename(path)
        with open(path, "rb") as f:
            content = base64.b64encode(f.read()).decode()

        api = f"https://api.github.com/repos/{GITHUB_USERNAME}/{GITHUB_REPO}/contents/slides/{name}"
        sha = requests.get(api, headers=headers).json().get("sha")

        payload = {"message":"20h Velo slide","content":content,"branch":GITHUB_BRANCH}
        if sha: payload["sha"] = sha

        requests.put(api, headers=headers, json=payload)
        urls.append(f"https://raw.githubusercontent.com/{GITHUB_USERNAME}/{GITHUB_REPO}/{GITHUB_BRANCH}/slides/{name}")

    return urls


# ---------------------------------------------
# MAIN
# ---------------------------------------------

def main():
    date_str = datetime.date.today().strftime("%Y-%m-%d")
    if verifier_cache(date_str):
        return

    articles = collecter_rss()
    if not articles:
        return

    post = generer_post(articles, determiner_type_post())
    images = generer_images(post)
    urls = uploader_images(images)

    sauvegarder_cache(date_str, post)


if __name__ == "__main__":
    main()

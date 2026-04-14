"""
LE 20H VELO — Script principal v6.0
Collecte l'actu cyclisme WorldTour, génère un post Instagram
via Gemini et publie automatiquement via Meta Graph API.

Fonctionnalités :
- Collecte RSS (médias + équipes WorldTour)
- Scraping classements UCI (ProCyclingStats) le lundi
- Scraping calendrier courses à venir le dimanche
- Slides "pépite" (infos de niche)
- Avant-course (présentation J-1/J-2)
- Design avec logo, barres couleur, numérotation
- Publication carrousel Instagram via Meta Graph API
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

# Couleurs du design
NOIR_FOND    = (15, 15, 20)
JAUNE_ACCENT = (232, 177, 0)
BLEU_ACCENT  = (58, 107, 159)
BLANC_TEXTE  = (240, 240, 240)
GRIS_SUBTLE  = (138, 138, 149)


# ---------------------------------------------
# SOURCES RSS
# ---------------------------------------------

RSS_SOURCES = [
    # --- Médias cyclisme ---
    {"nom": "Cyclingnews",     "url": "https://www.cyclingnews.com/rss.xml"},
    {"nom": "Cyclism'Actu",    "url": "https://www.cyclismactu.net/feed"},
    {"nom": "VeloNews",        "url": "https://www.velonews.com/feed"},
    {"nom": "Sporza",          "url": "https://sporza.be/nl/categorie/wielrennen.rss.xml"},
    {"nom": "RTBF Sport",      "url": "https://www.rtbf.be/api/dyn?action=get_article_list&cat=sp_cyclisme&output=rss"},
    {"nom": "DirectVelo",      "url": "https://www.directvelo.com/rss"},
    {"nom": "Wielerflits",     "url": "https://www.wielerflits.nl/feed/"},
    {"nom": "ProCyclingStats", "url": "https://www.procyclingstats.com/rss.php"},
    {"nom": "FirstCycling",    "url": "https://firstcycling.com/rss.php"},
    # --- Equipes WorldTour ---
    {"nom": "Visma-LAB",          "url": "https://www.teamvisma-leaseabike.com/feed"},
    {"nom": "UAE Team Emirates",  "url": "https://www.uaeteamemirates.com/feed/"},
    {"nom": "Soudal Quick-Step",  "url": "https://www.soudal-quickstepteam.com/feed"},
    {"nom": "INEOS Grenadiers",   "url": "https://www.ineosgrenadiers.com/feed"},
    {"nom": "Lidl-Trek",          "url": "https://www.lidl-trek.com/feed"},
    {"nom": "Alpecin-Deceuninck", "url": "https://www.alpecin-deceuninck.com/en/feed"},
    {"nom": "Intermarché-Wanty",  "url": "https://www.intermarche-wanty.com/feed"},
    {"nom": "Lotto-Dstny",        "url": "https://www.lfrvcycling.com/feed"},
    {"nom": "Bahrain Victorious", "url": "https://www.teambahrainvictorious.com/feed"},
    {"nom": "Movistar Team",      "url": "https://www.movistarteam.com/feed"},
    {"nom": "EF Education",       "url": "https://www.efprocycling.com/feed"},
    {"nom": "Jayco-AlUla",        "url": "https://www.greenedge.bike/feed"},
    {"nom": "Bora-Hansgrohe",     "url": "https://www.bfrvcycling.com/feed"},
]

KEYWORDS_WORLDTOUR = [
    "worldtour", "tour de france", "giro", "vuelta",
    "paris-roubaix", "flandres", "liege", "sanremo",
    "lombardie", "amstel", "strade", "tirreno",
    "paris-nice", "criterium", "uci", "peloton",
    "pro cycling", "stage", "etape", "classement",
    "victoire", "winner", "sprint", "breakaway",
    "gc", "general classification", "maillot jaune",
    "maillot rose", "maglia rosa", "leader",
    "transfer", "transfert", "signe", "contrat",
    "injured", "bless", "abandon", "chute", "crash",
    "sponsor", "partenaire", "coach", "entraineur",
    "directeur sportif", "neo-pro", "stagiaire",
    "materiel", "velo", "cadre", "prolongation",
    "rejoint", "quitte", "startlist", "depart",
    "reconnaissance", "presentation", "equipe",
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
- Tu ne peux utiliser QUE les informations contenues dans les articles
  et données fournis (articles RSS, classements UCI, calendrier)
- AUCUN fait, résultat, classement, citation, statistique ou temps ne peut
  être inventé, déduit, extrapolé ou complété de mémoire
- Si un article dit "Evenepoel a gagné", tu peux écrire qu'il a gagné.
  Si l'article ne mentionne pas le temps, tu ne donnes PAS de temps.
- Si une info est présentée comme rumeur dans la source, utilise
  le conditionnel ("pourrait", "serait", "selon X")
- Chaque fait doit être traçable aux données fournies
- Si tu n'as pas assez de contenu, fais MOINS de slides.
  3 slides fiables valent mieux que 6 slides avec du remplissage inventé.
- En cas de doute sur une info : ne pas l'inclure

QUAND CITER LA SOURCE DANS LE TEXTE :
- Ne PAS citer la source systématiquement sur chaque slide
- Citer UNIQUEMENT quand c'est journalistiquement nécessaire :
  • Une exclu ou un scoop : "Selon la RTBF, Evenepoel pourrait…"
  • Une rumeur non confirmée : "D'après Cyclingnews, un transfert…"
  • Des infos contradictoires entre sources
  • Une citation directe d'un coureur ou directeur sportif
- Résultats et faits établis : pas besoin de citer la source

TON ET STYLE :
- Décontracté, naturel, entre passionnés de cyclisme
- Jargon vélo bienvenu (peloton, baroud, bidon, musette, flamme rouge…)
- Pas d'adresse directe au lecteur (pas de tu/vous)
- Humour léger si ça vient naturellement, jamais forcé
- Emojis : max 2 dans la légende, ZÉRO dans les slides

STRUCTURE DU CARROUSEL :
- Slide 1 = TOUJOURS une couverture : titre "LE 20H VELO" + date du jour
  (contenu : une phrase d'accroche résumant le post du jour)
- Slides suivantes = contenu selon le type de post
- Nombre total de slides (couverture incluse) : 3 minimum, 6 maximum

SLIDES "PÉPITE" — INFOS DE NICHE :
- Inclure 1 à 2 slides d'infos moins grand public si disponibles
- Types : néo-pro qui signe, changement d'entraîneur ou de directeur
  sportif, nouveau sponsor, changement de matériel, retour discret
  de blessure, résultat en course secondaire, prolongation de contrat
  inattendue, départ d'un staff, arrivée d'un partenaire technique
- Préfixer le titre avec "PÉPITE |" (ex: "PÉPITE | Nouveau coach Visma")
- Si aucune info niche dans les articles, ne pas en inventer
- Les pépites s'ajoutent aux infos principales

AVANT-COURSE (J-1 ou J-2 d'une grande course) :
- Si les articles mentionnent une course à venir dans les 1-2 jours,
  consacrer 1-2 slides à la présentation de cette course
- Contenu : équipes favorites, coureurs à suivre, absents notables,
  surprises potentielles — UNIQUEMENT basé sur les articles fournis
- Maximum 2 courses traitées par post (les 2 plus importantes)

TYPE "classements" (lundi) :
- Une slide dédiée aux classements UCI fournis dans les données
- Top 10 individuel + Top 5 équipes sur la même slide
- Mentionner les mouvements importants (entrées/sorties du top 20,
  progressions notables, équipes en difficulté)
- Rester STRICTEMENT factuel : utiliser les données classement fournies
- Le reste des slides = actu normale du jour

TYPE "calendrier" (dimanche) :
- La dernière slide = programme des courses de la semaine à venir
- Utiliser les données calendrier fournies
- Mentionner les courses les plus importantes de la semaine
- Le reste des slides = actu normale du jour

ANGLE BELGE :
- Mentionner coureurs/équipes belges quand l'actu s'y prête
- Ne pas forcer si rien de belge dans les articles du jour

CONTENU PAR SLIDE :
- Titre : max 6 mots, percutant
- Contenu : le fait clé + pourquoi c'est important (max 280 caractères)

JSON UNIQUEMENT — format strict :
{"type":"<general|classements|calendrier>","legende":"<1-2 phrases>","slides":[{"numero":1,"titre":"<max 6 mots>","contenu":"<max 280 car>","source":"<nom>","lien":"<url>"}],"hashtags":["#tag"]}

Les champs "source" et "lien" servent à la traçabilité interne.
Pour la slide couverture, source = "20H VELO" et lien = "".
Pour les slides classement/calendrier, source = "ProCyclingStats" et lien = "".

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
            for entry in feed.entries[:15]:
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
        time.sleep(0.5)

    # Dédupliquer par titre similaire
    seen_titles = set()
    unique_articles = []
    for a in articles:
        title_key = a["titre"].lower()[:50]
        if title_key not in seen_titles:
            seen_titles.add(title_key)
            unique_articles.append(a)

    unique_articles.sort(key=lambda x: x["est_belge"], reverse=True)
    return unique_articles


# ---------------------------------------------
# 3. SCRAPING CLASSEMENTS UCI (lundi)
# ---------------------------------------------

def scraper_classements_uci():
    """Scrape les classements UCI individuels et par équipes sur PCS."""
    resultats = {"individuel": [], "equipes": []}

    # Classement individuel
    try:
        url = "https://www.procyclingstats.com/rankings.php"
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table", class_="basic")
        if table:
            rows = table.find_all("tr")[1:21]  # Top 20
            for row in rows:
                cols = row.find_all("td")
                if len(cols) >= 4:
                    rang = cols[0].get_text(strip=True)
                    nom = cols[2].get_text(strip=True)
                    equipe = cols[3].get_text(strip=True) if len(cols) > 3 else ""
                    points = cols[-1].get_text(strip=True)
                    resultats["individuel"].append({
                        "rang": rang, "nom": nom,
                        "equipe": equipe, "points": points,
                    })
        print(f"  📊 Classement individuel : {len(resultats['individuel'])} coureurs")
    except Exception as e:
        print(f"  ⚠️  Erreur scraping classement individuel : {e}")

    # Classement par équipes
    try:
        url = "https://www.procyclingstats.com/rankings/me/teams"
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table", class_="basic")
        if table:
            rows = table.find_all("tr")[1:11]  # Top 10
            for row in rows:
                cols = row.find_all("td")
                if len(cols) >= 3:
                    rang = cols[0].get_text(strip=True)
                    equipe = cols[1].get_text(strip=True)
                    points = cols[-1].get_text(strip=True)
                    resultats["equipes"].append({
                        "rang": rang, "equipe": equipe, "points": points,
                    })
        print(f"  📊 Classement équipes : {len(resultats['equipes'])} équipes")
    except Exception as e:
        print(f"  ⚠️  Erreur scraping classement équipes : {e}")

    return resultats


# ---------------------------------------------
# 4. SCRAPING CALENDRIER (dimanche)
# ---------------------------------------------

def scraper_calendrier_semaine():
    """Scrape les courses de la semaine à venir sur PCS."""
    courses = []
    try:
        aujourd_hui = datetime.date.today()
        # Chercher les courses des 7 prochains jours
        url = f"https://www.procyclingstats.com/races.php?year={aujourd_hui.year}&circuit=1&class=&filter=Filter"
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table", class_="basic")
        if table:
            rows = table.find_all("tr")[1:]
            for row in rows:
                cols = row.find_all("td")
                if len(cols) >= 3:
                    dates = cols[0].get_text(strip=True)
                    nom = cols[1].get_text(strip=True)
                    categorie = cols[2].get_text(strip=True) if len(cols) > 2 else ""
                    courses.append({
                        "dates": dates, "nom": nom, "categorie": categorie,
                    })
        # Filtrer les courses dans les 7 prochains jours
        # (garder les 10 premières comme approximation)
        courses = courses[:10]
        print(f"  📅 Calendrier : {len(courses)} courses trouvées")
    except Exception as e:
        print(f"  ⚠️  Erreur scraping calendrier : {e}")

    return courses


# ---------------------------------------------
# 5. TYPE DE POST
# ---------------------------------------------

def determiner_type_post():
    jour = datetime.date.today().weekday()
    mois = datetime.date.today().month

    if jour == 0:  # Lundi
        return "classements"
    if jour == 6:  # Dimanche
        return "calendrier"
    return "general"


# ---------------------------------------------
# 6. GENERATION VIA GEMINI
# ---------------------------------------------

def generer_post(articles, type_post, classements=None, calendrier=None):
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(
        "gemini-3-flash-preview",
        system_instruction=SYSTEM_PROMPT,
    )

    # Articles (max 8 pour le free tier)
    articles_txt = "\n".join([
        f"- [{a['source']}] {a['titre']} | {a['lien']}"
        f"{' (BELGE)' if a['est_belge'] else ''}"
        for a in articles[:8]
    ])

    # Données supplémentaires selon le type
    extra_data = ""

    if type_post == "classements" and classements:
        extra_data += "\n\n═══ CLASSEMENTS UCI (données exactes) ═══\n"
        extra_data += "TOP 10 INDIVIDUEL :\n"
        for c in classements["individuel"][:10]:
            extra_data += f"  {c['rang']}. {c['nom']} ({c['equipe']}) — {c['points']} pts\n"
        extra_data += "\nTOP 5 EQUIPES :\n"
        for c in classements["equipes"][:5]:
            extra_data += f"  {c['rang']}. {c['equipe']} — {c['points']} pts\n"

    if type_post == "calendrier" and calendrier:
        extra_data += "\n\n═══ CALENDRIER SEMAINE À VENIR ═══\n"
        for c in calendrier:
            extra_data += f"  {c['dates']} — {c['nom']} ({c['categorie']})\n"

    prompt = (
        f"Type: {type_post} | Date: {datetime.date.today().strftime('%d %B %Y')}\n"
        f"Slides: 3-6\n\n"
        f"Articles:\n{articles_txt}"
        f"{extra_data}\n\n"
        f"JSON:"
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
# 7. GENERATION DES IMAGES
# ---------------------------------------------

def charger_logo():
    try:
        logo = Image.open("assets/logo.png").convert("RGBA")
        logo = logo.resize((120, 120), Image.LANCZOS)
        return logo
    except FileNotFoundError:
        print("⚠️  Logo non trouvé dans assets/logo.png")
        return None


def dessiner_barre_haut(draw):
    draw.rectangle([(0, 0), (1080, 6)], fill=JAUNE_ACCENT)


def dessiner_barre_bas(draw):
    draw.rectangle([(0, 1074), (1080, 1080)], fill=BLEU_ACCENT)


def generer_slide_couverture(post, logo, font_titre, font_txt, font_small):
    img = Image.new("RGB", (1080, 1080), NOIR_FOND)
    draw = ImageDraw.Draw(img)

    dessiner_barre_haut(draw)
    dessiner_barre_bas(draw)

    if logo:
        x_logo = (1080 - logo.width) // 2
        img.paste(logo, (x_logo, 80), logo)
        y_start = 220
    else:
        draw.text((390, 80), "LE", fill=JAUNE_ACCENT, font=font_small)
        draw.text((370, 110), "20H", fill=BLANC_TEXTE, font=font_titre)
        draw.text((340, 190), "VÉLO", fill=JAUNE_ACCENT, font=font_titre)
        y_start = 300

    # Ligne séparation
    draw.line([(340, y_start), (740, y_start)], fill=JAUNE_ACCENT, width=2)

    # Date
    date_txt = datetime.date.today().strftime("%d %B %Y").upper()
    bbox = draw.textbbox((0, 0), date_txt, font=font_small)
    date_w = bbox[2] - bbox[0]
    draw.text(((1080 - date_w) // 2, y_start + 20), date_txt,
              fill=GRIS_SUBTLE, font=font_small)

    # Type badge
    type_post = post.get("type", "general")
    badge_txt = ""
    if type_post == "classements":
        badge_txt = "CLASSEMENTS UCI"
    elif type_post == "calendrier":
        badge_txt = "PROGRAMME DE LA SEMAINE"

    if badge_txt:
        bbox = draw.textbbox((0, 0), badge_txt, font=font_small)
        badge_w = bbox[2] - bbox[0]
        draw.text(((1080 - badge_w) // 2, y_start + 55), badge_txt,
                  fill=BLEU_ACCENT, font=font_small)

    # Accroche
    slide_couverture = post["slides"][0]
    y = y_start + 100
    for chunk in textwrap.wrap(slide_couverture["contenu"], 35):
        bbox = draw.textbbox((0, 0), chunk, font=font_txt)
        chunk_w = bbox[2] - bbox[0]
        draw.text(((1080 - chunk_w) // 2, y), chunk,
                  fill=BLANC_TEXTE, font=font_txt)
        y += 48

    return img


def generer_slide_contenu(slide, num, total, logo, font_titre, font_txt, font_small):
    img = Image.new("RGB", (1080, 1080), NOIR_FOND)
    draw = ImageDraw.Draw(img)

    dessiner_barre_haut(draw)
    dessiner_barre_bas(draw)

    # Header : logo petit à gauche + numéro à droite
    if logo:
        petit_logo = logo.resize((50, 50), Image.LANCZOS)
        img.paste(petit_logo, (40, 30), petit_logo)
    else:
        draw.text((40, 35), "20H VÉLO", fill=JAUNE_ACCENT, font=font_small)

    num_txt = f"{num} / {total}"
    bbox = draw.textbbox((0, 0), num_txt, font=font_small)
    num_w = bbox[2] - bbox[0]
    draw.text((1080 - 40 - num_w, 42), num_txt, fill=GRIS_SUBTLE, font=font_small)

    # Détection pépite
    is_pepite = slide["titre"].upper().startswith("PÉPITE")
    titre_color = BLEU_ACCENT if is_pepite else JAUNE_ACCENT

    # Titre
    y = 110
    titre_lines = textwrap.wrap(slide["titre"].upper(), 26)
    for line in titre_lines:
        draw.text((60, y), line, fill=titre_color, font=font_titre)
        y += 58

    # Trait de séparation
    y += 15
    sep_color = JAUNE_ACCENT if is_pepite else BLEU_ACCENT
    draw.line([(60, y), (160, y)], fill=sep_color, width=3)
    y += 30

    # Contenu en blanc
    for ligne in slide["contenu"].split("\n"):
        for chunk in textwrap.wrap(ligne, 36):
            draw.text((60, y), chunk, fill=BLANC_TEXTE, font=font_txt)
            y += 46

    return img


def generer_images(post):
    os.makedirs("slides", exist_ok=True)
    images = []

    try:
        font_titre = ImageFont.truetype("fonts/Inter-Bold.ttf", 48)
        font_txt   = ImageFont.truetype("fonts/Inter-Regular.ttf", 34)
        font_small = ImageFont.truetype("fonts/Inter-Regular.ttf", 24)
    except IOError:
        print("⚠️  Polices Inter non trouvées, utilisation de la police par défaut")
        font_titre = font_txt = font_small = ImageFont.load_default()

    logo = charger_logo()
    total = len(post["slides"])

    for i, slide in enumerate(post["slides"]):
        if i == 0:
            img = generer_slide_couverture(
                post, logo, font_titre, font_txt, font_small
            )
        else:
            img = generer_slide_contenu(
                slide, i + 1, total, logo, font_titre, font_txt, font_small
            )

        path = f"slides/slide_{i + 1}.jpg"
        img.save(path, "JPEG", quality=95)
        images.append(path)

    return images


# ---------------------------------------------
# 8. UPLOAD DES IMAGES SUR GITHUB (un seul commit)
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
# 9. PUBLICATION INSTAGRAM (carrousel)
# ---------------------------------------------

def publier_instagram(post, images):
    base_url = "https://graph.facebook.com/v25.0"

    print("  📤 Upload des images sur GitHub...")
    image_urls = upload_images_github(images)

    print("  ⏳ Attente propagation GitHub (15s)...")
    time.sleep(15)

    print("  📦 Création des containers Instagram...")
    container_ids = []

    for image_url in image_urls:
        resp = requests.post(
            f"{base_url}/{INSTAGRAM_ACCOUNT_ID}/media",
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

    # Construire la légende avec les liens
    legende = post["legende"] + "\n\n"
    liens_trouves = False
    for slide in post["slides"]:
        if slide.get("lien") and slide["lien"] and slide["numero"] > 1:
            if not liens_trouves:
                legende += "📰 Sources :\n"
                liens_trouves = True
            legende += f"➤ {slide['titre']} : {slide['lien']}\n"
    legende += "\n" + " ".join(post["hashtags"])

    # Créer le carrousel
    print("  🎠 Création du carrousel...")
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
# 10. MAIN
# ---------------------------------------------

def main():
    print("=" * 50)
    print("LE 20H VELO — Publication automatique v6.0")
    print("=" * 50)

    date_str = datetime.date.today().isoformat()

    if verifier_cache(date_str):
        print(f"⏭️  Post déjà généré pour {date_str}, on skip.")
        return

    # Collecte RSS
    print("\n📡 Collecte des articles RSS...")
    articles = collecter_rss()

    if not articles:
        print("⚠️  Aucun article WorldTour trouvé aujourd'hui. Abandon.")
        return

    print(f"📰 {len(articles)} articles trouvés")
    belges = sum(1 for a in articles if a["est_belge"])
    if belges:
        print(f"   dont {belges} article(s) belge(s)")

    # Type de post
    type_post = determiner_type_post()
    print(f"\n📝 Type de post du jour : {type_post}")

    # Données supplémentaires selon le jour
    classements = None
    calendrier = None

    if type_post == "classements":
        print("\n📊 Scraping des classements UCI...")
        classements = scraper_classements_uci()

    if type_post == "calendrier":
        print("\n📅 Scraping du calendrier de la semaine...")
        calendrier = scraper_calendrier_semaine()

    # Génération du contenu via Gemini
    print("\n🤖 Génération du contenu via Gemini...")
    post = generer_post(articles, type_post, classements, calendrier)
    print(f"   {len(post['slides'])} slides générées")

    # Génération des images
    print("\n🎨 Génération des images...")
    images = generer_images(post)
    print(f"   {len(images)} images créées")

    # Publication Instagram
    print("\n📤 Publication sur Instagram...")
    publier_instagram(post, images)

    # Sauvegarder le cache
    sauvegarder_cache(date_str, post)

    print("\n" + "=" * 50)
    print("✅ LE 20H VELO — Terminé avec succès !")
    print("=" * 50)


if __name__ == "__main__":
    main()

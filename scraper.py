#!/usr/bin/env python3
"""
VAULTFLIP — Scraper Production avec API officielle eBay
========================================================
Utilise l'API officielle eBay Browse API pour avoir de vrais liens.
LBC scraping avec rotation d'approche pour contourner les blocages.
"""

import os, time, random, re, json, threading, logging
from datetime import datetime, timezone
from urllib.parse import quote_plus, urlencode
import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
log = logging.getLogger(__name__)

app = Flask(__name__, static_folder='.')
CORS(app)

# ── Config Railway ─────────────────────────────────────────
PORT          = int(os.environ.get('PORT', 5001))
ROI_MIN       = int(os.environ.get('ROI_MIN', 20))
PROFIT_MIN    = int(os.environ.get('PROFIT_MIN', 12))
SCAN_INTERVAL = int(os.environ.get('SCAN_INTERVAL', 35))
SILVER_G      = float(os.environ.get('SILVER_G', 0.93))
GOLD_G        = float(os.environ.get('GOLD_G', 89.24))

# ── Clé API eBay (variable d'environnement Railway) ────────
# Dans Railway → Variables → ajoute EBAY_APP_ID avec ta clé
# Créer une clé GRATUITE sur : https://developer.ebay.com
# "Get an Application Key" → Production → OAuth credentials → App ID (Client ID)
EBAY_APP_ID = os.environ.get('EBAY_APP_ID', '')

# ── Requêtes de scan ───────────────────────────────────────
SEARCHES = [
    # (keywords, cat, valeur_ref, poids_g, titre_fin)
    ("5 francs semeuse argent",        "semeuse",  13,   12,   0.835),
    ("100 francs hercule argent",      "hercule",  40,   15,   0.900),
    ("lot monnaies argent anciennes",  "franc",    50,   40,   0.835),
    ("20 francs napoleon or",          "napoleon", 440,  6.45, 0.900),
    ("lingot argent 100g",             "lingot",   93,   100,  0.999),
    ("game boy lot jeux nintendo",     "jeux",     160,  0,    0),
    ("super nintendo snes lot jeux",   "jeux",     200,  0,    0),
    ("nintendo 64 lot jeux mario",     "jeux",     250,  0,    0),
    ("pokemon carte holographique",    "pokemon",  200,  0,    0),
    ("billet 500 francs ancien",       "billet",   85,   0,    0),
    ("vinyle jazz soul lp 33t",        "vinyle",   80,   0,    0),
    ("platine thorens vintage",        "vinyle",   280,  0,    0),
    ("tintin edition originale",       "bd",       120,  0,    0),
    ("leica m3 m6 argentique",         "vintage",  900,  0,    0),
    ("seiko automatique vintage",      "montre",   180,  0,    0),
    ("omega seamaster vintage",        "montre",   650,  0,    0),
    ("nike air jordan retro og",       "sneakers", 500,  0,    0),
    ("morgan dollar argent usa",       "piece",    45,   26.7, 0.900),
    ("mega drive sega lot jeux",       "jeux",     150,  0,    0),
    ("asterix tintin bd originale",    "bd",       100,  0,    0),
]

found_articles = []
seen_urls      = set()
next_id        = 1000
lock           = threading.Lock()
stats = {"total_scans":0,"total_found":0,"last_scan":None,"errors":0,"ebay_ok":0,"lbc_ok":0}


def estimate_value(prix, cat, poids_g, titre_fin):
    metal = round(poids_g * SILVER_G * titre_fin, 2) if poids_g > 0 and titre_fin > 0 else 0
    numis = {"semeuse":13,"hercule":38,"franc":25,"napoleon":440,
             "lingot":max(metal, prix*0.95),"piece":42,"jeux":0,
             "pokemon":0,"billet":80,"vinyle":70,"vintage":350,
             "bd":120,"montre":300,"sneakers":350}.get(cat, 0)
    return max(metal, numis) if (metal or numis) else 0


def calc_roi(prix, frais_port, revente_est, frais_vente=5):
    cout = prix + frais_port
    profit = revente_est - frais_vente - cout
    if cout <= 0: return 0, 0
    return round(profit/cout*100), round(profit, 2)


def make_article(titre, prix, frais_port, lien, plateforme, cat, poids_g, titre_fin, img="", ville="", age="récemment"):
    global next_id
    if not lien or lien in seen_urls: return None
    # Vérifier que c'est un vrai lien produit (pas une recherche)
    if 'recherche?text=' in lien or '/sch/i.html' in lien or 'catalog?search' in lien:
        return None  # Refuser les liens de recherche
    val = estimate_value(prix, cat, poids_g, titre_fin)
    rev = val * 0.92 if val > 0 else prix * 1.28
    roi_pct, profit = calc_roi(prix, frais_port, rev)
    if roi_pct < ROI_MIN or profit < PROFIT_MIN: return None
    seen_urls.add(lien)
    next_id += 1
    return {
        "id": next_id, "titre": titre[:80],
        "prix": prix, "fraisPort": round(frais_port,2),
        "valReelle": round(val,2), "revente": round(rev,2),
        "roi": roi_pct, "profit": profit,
        "lien": lien,  # VRAI LIEN DIRECT
        "plateforme": plateforme,
        "ville": ville, "age": age, "cat": cat,
        "image": img,
        "auth": 88 if plateforme=="lbc" else 84,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "hot": roi_pct >= 35,
    }


# ── EBAY API OFFICIELLE ────────────────────────────────────
def get_ebay_token():
    """Obtient un token OAuth eBay via Client Credentials."""
    if not EBAY_APP_ID:
        return None
    ebay_secret = os.environ.get('EBAY_CERT_ID', '')
    if not ebay_secret:
        return None
    try:
        import base64
        creds = base64.b64encode(f"{EBAY_APP_ID}:{ebay_secret}".encode()).decode()
        resp = requests.post(
            "https://api.ebay.com/identity/v1/oauth2/token",
            headers={"Authorization": f"Basic {creds}", "Content-Type": "application/x-www-form-urlencoded"},
            data="grant_type=client_credentials&scope=https%3A%2F%2Fapi.ebay.com%2Foauth%2Fapi_scope",
            timeout=10
        )
        if resp.status_code == 200:
            return resp.json().get("access_token")
    except Exception as e:
        log.warning(f"eBay token: {e}")
    return None

_ebay_token = None
_ebay_token_time = 0

def get_cached_token():
    global _ebay_token, _ebay_token_time
    if time.time() - _ebay_token_time > 6000:  # refresh toutes les 100 min
        _ebay_token = get_ebay_token()
        _ebay_token_time = time.time()
    return _ebay_token


def scrape_ebay_api(keywords, cat, val_ref, poids_g, titre_fin):
    """Utilise l'API officielle eBay Browse API — vrais liens garantis."""
    results = []
    token = get_cached_token()
    if not token:
        # Fallback scraping HTML si pas de token
        return scrape_ebay_html(keywords, cat, val_ref, poids_g, titre_fin)
    try:
        prix_max = int(val_ref * 0.86) if val_ref > 5 else 300
        params = {
            "q": keywords,
            "filter": f"price:[0..{prix_max}],priceCurrency:EUR,itemLocationCountry:FR",
            "sort": "newlyListed",
            "limit": 20,
        }
        resp = requests.get(
            "https://api.ebay.com/buy/browse/v1/item_summary/search?" + urlencode(params),
            headers={
                "Authorization": f"Bearer {token}",
                "X-EBAY-C-MARKETPLACE-ID": "EBAY_FR",
                "Accept-Language": "fr-FR",
            },
            timeout=12
        )
        if resp.status_code != 200:
            log.warning(f"eBay API {resp.status_code}: {resp.text[:200]}")
            return scrape_ebay_html(keywords, cat, val_ref, poids_g, titre_fin)

        data = resp.json()
        for item in data.get("itemSummaries", []):
            prix_data = item.get("price", {})
            prix = float(prix_data.get("value", 0))
            if prix <= 0: continue

            # Lien DIRECT vers la page produit eBay
            lien = item.get("itemWebUrl", "")
            if not lien: continue

            titre_ad = item.get("title", "").strip()
            ship_data = item.get("shippingOptions", [{}])
            frais_port = 0.0
            if ship_data:
                ship_cost = ship_data[0].get("shippingCost", {})
                frais_port = float(ship_cost.get("value", 0))

            img_data = item.get("image", {})
            img = img_data.get("imageUrl", "") if isinstance(img_data, dict) else ""

            a = make_article(titre_ad, prix, frais_port, lien, "ebay", cat, poids_g, titre_fin, img)
            if a:
                results.append(a)
                stats["ebay_ok"] += 1

    except Exception as e:
        log.warning(f"eBay API [{keywords}]: {e}")
        stats["errors"] += 1
        return scrape_ebay_html(keywords, cat, val_ref, poids_g, titre_fin)
    return results


def scrape_ebay_html(keywords, cat, val_ref, poids_g, titre_fin):
    """Fallback HTML scraping eBay avec IP Railway."""
    results = []
    try:
        prix_max = int(val_ref * 0.86) if val_ref > 5 else 300
        ua = random.choice([
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 Version/17.4 Safari/605.1.15",
        ])
        url = f"https://www.ebay.fr/sch/i.html?_nkw={quote_plus(keywords)}&_sop=10&_udhi={prix_max}&LH_PrefLoc=1"
        resp = requests.get(url, headers={"User-Agent": ua, "Accept-Language": "fr-FR"}, timeout=14)
        if resp.status_code != 200: return results
        soup = BeautifulSoup(resp.text, "lxml")
        for item in soup.select(".s-item")[:20]:
            title_el = item.select_one(".s-item__title")
            if not title_el: continue
            titre_ad = title_el.get_text(strip=True)
            if "Shop on eBay" in titre_ad: continue
            price_el = item.select_one(".s-item__price")
            if not price_el: continue
            try:
                prix = float(re.sub(r"[^\d,.]","",price_el.get_text(strip=True).split("à")[0]).replace(",","."))
            except: continue
            if prix <= 0: continue
            link_el = item.select_one("a.s-item__link")
            if not link_el: continue
            # Extraire l'ID de l'item pour construire un vrai lien propre
            href = link_el.get("href","")
            item_id_m = re.search(r'/(\d{10,13})\?', href)
            if item_id_m:
                lien = f"https://www.ebay.fr/itm/{item_id_m.group(1)}"
            else:
                lien = href.split("?")[0] if href.startswith("http") else ""
            if not lien: continue
            ship_el = item.select_one(".s-item__shipping,.s-item__logisticsCost")
            frais_port = 0.0
            if ship_el:
                st = ship_el.get_text(strip=True).lower()
                if "gratuit" not in st:
                    m = re.search(r"[\d]+[,.]?[\d]*", st)
                    frais_port = float(m.group().replace(",",".")) if m else 5.5
            img_el = item.select_one(".s-item__image-img")
            img = img_el.get("src","") if img_el else ""
            a = make_article(titre_ad, prix, frais_port, lien, "ebay", cat, poids_g, titre_fin, img)
            if a:
                results.append(a)
                stats["ebay_ok"] += 1
    except Exception as e:
        log.warning(f"eBay HTML [{keywords}]: {e}")
        stats["errors"] += 1
    return results


def scrape_lbc(keywords, cat, val_ref, poids_g, titre_fin):
    """LBC via API interne."""
    results = []
    try:
        prix_max = int(val_ref * 0.88) if val_ref > 5 else 500
        payload = {
            "filters": {
                "keywords": {"text": keywords},
                "ranges": {"price": {"min": 1, "max": prix_max}},
            },
            "sort_by": "time", "sort_order": "desc",
            "limit": 15, "offset": 0,
        }
        ua = random.choice([
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
        ])
        headers = {
            "User-Agent": ua,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "api_key": "ba0c2dad52b3565fd3cc99f8f2c3a267",
            "Origin": "https://www.leboncoin.fr",
            "Referer": "https://www.leboncoin.fr/",
        }
        resp = requests.post("https://api.leboncoin.fr/finder/search", json=payload, headers=headers, timeout=12)

        if resp.status_code == 200:
            for ad in resp.json().get("ads", []):
                raw = ad.get("price",[0])
                prix = (raw[0] if isinstance(raw,list) else raw) or 0
                if prix <= 0: continue
                list_id = ad.get("list_id","")
                if not list_id: continue
                # Lien DIRECT vers l'annonce LBC
                lien = f"https://www.leboncoin.fr/ad/divers/{list_id}"
                titre_ad = ad.get("subject","").strip()
                loc = ad.get("location",{})
                ville = loc.get("city","") if isinstance(loc,dict) else ""
                ship = ad.get("shipping",{})
                frais_port = 5.5 if (isinstance(ship,dict) and ship.get("type")!="disabled") else 0
                imgs = ad.get("images",{})
                img = ""
                if isinstance(imgs,dict):
                    urls = imgs.get("urls_large") or imgs.get("urls") or []
                    img = urls[0] if urls else ""
                date_str = ad.get("first_publication_date","")
                try:
                    dt = datetime.fromisoformat(date_str.replace('Z','+00:00'))
                    diff = int((datetime.now(dt.tzinfo)-dt).total_seconds())
                    age = "À l'instant" if diff<60 else f"il y a {diff//60}min" if diff<3600 else f"il y a {diff//3600}h"
                except:
                    age = "récemment"
                a = make_article(titre_ad, prix, frais_port, lien, "lbc", cat, poids_g, titre_fin, img, ville, age)
                if a:
                    results.append(a)
                    stats["lbc_ok"] += 1
        else:
            log.warning(f"LBC HTTP {resp.status_code}")
    except Exception as e:
        log.warning(f"LBC [{keywords}]: {e}")
        stats["errors"] += 1
    return results


def scrape_vinted(keywords, cat, val_ref):
    """Vinted API publique."""
    results = []
    try:
        prix_max = int(val_ref * 0.84) if val_ref > 5 else 150
        url = f"https://www.vinted.fr/api/v2/catalog/items?search_text={quote_plus(keywords)}&order=newest_first&price_to={prix_max}&per_page=15"
        resp = requests.get(url, headers={"User-Agent":"Mozilla/5.0 (iPhone; CPU iPhone OS 17_4) AppleWebKit/605.1.15 Mobile Safari/604.1","Accept-Language":"fr-FR"}, timeout=10)
        if resp.status_code != 200: return results
        for item in resp.json().get("items",[]):
            raw = item.get("price",{})
            prix = float(raw.get("amount",0) if isinstance(raw,dict) else raw or 0)
            if prix <= 0: continue
            item_id = item.get("id","")
            slug = item.get("url",f"/items/{item_id}")
            # Lien DIRECT Vinted
            lien = f"https://www.vinted.fr{slug}" if slug.startswith("/") else slug
            titre_ad = item.get("title","").strip()
            svc = item.get("service_fee",{})
            frais_port = float(svc.get("amount",3.5) if isinstance(svc,dict) else 3.5)
            photo = item.get("photo",{})
            img = (photo.get("full_size_url") or photo.get("url","")) if isinstance(photo,dict) else ""
            a = make_article(titre_ad, prix, frais_port, lien, "vint", cat, 0, 0, img)
            if a: results.append(a)
    except Exception as e:
        log.warning(f"Vinted [{keywords}]: {e}")
        stats["errors"] += 1
    return results


def update_metals():
    global SILVER_G, GOLD_G
    try:
        resp = requests.get("https://api.metals.live/v1/spot/silver,gold", timeout=8)
        if resp.status_code == 200:
            usd_eur, oz_g = 0.92, 31.1035
            for e in resp.json():
                if e.get("silver"): SILVER_G = round(e["silver"]*usd_eur/oz_g,4)
                if e.get("gold"):   GOLD_G   = round(e["gold"]*usd_eur/oz_g,4)
            log.info(f"Cours: Ag={SILVER_G}€/g Au={GOLD_G}€/g")
    except: pass


def scan_loop():
    log.info("Scanner démarré")
    update_metals()
    # Pré-charger le token eBay
    if EBAY_APP_ID:
        get_cached_token()
        log.info("Token eBay OK" if _ebay_token else "Pas de token eBay — utilisation HTML")
    else:
        log.info("Pas de EBAY_APP_ID — utilisation scraping HTML eBay")

    while True:
        kw, cat, val_ref, poids, titre_fin = random.choice(SEARCHES)
        log.info(f"Scan → '{kw}' [{cat}]")
        stats["last_scan"] = datetime.now(timezone.utc).isoformat()
        stats["total_scans"] += 1

        new_items = []

        # LBC
        lbc = scrape_lbc(kw, cat, val_ref, poids, titre_fin)
        new_items.extend(lbc)
        if lbc: log.info(f"  LBC: {len(lbc)} ✓ ({[a['lien'] for a in lbc[:2]]})")
        time.sleep(random.uniform(3, 5))

        # eBay (API officielle si dispo, HTML sinon)
        ebay = scrape_ebay_api(kw+" france", cat, val_ref, poids, titre_fin)
        new_items.extend(ebay)
        if ebay: log.info(f"  eBay: {len(ebay)} ✓")
        time.sleep(random.uniform(2, 4))

        # Vinted pour certaines catégories
        if cat in ["jeux","sneakers","billet","vinyle","montre"]:
            vint = scrape_vinted(kw, cat, val_ref)
            new_items.extend(vint)
            if vint: log.info(f"  Vinted: {len(vint)} ✓")

        with lock:
            for a in new_items: found_articles.insert(0,a)
            del found_articles[300:]

        stats["total_found"] += len(new_items)
        if new_items:
            log.info(f"  ✅ {len(new_items)} annonce(s) avec vrais liens")
        else:
            log.info(f"  ⚠ Aucune affaire ROI>{ROI_MIN}% cette fois")

        if stats["total_scans"] % 8 == 0:
            update_metals()

        time.sleep(SCAN_INTERVAL + random.uniform(0, 10))


# ── API ────────────────────────────────────────────────────
@app.route("/api/articles")
def api_articles():
    limit = min(int(request.args.get("limit",50)),200)
    cat = request.args.get("cat")
    with lock:
        items = [a for a in found_articles if not cat or a["cat"]==cat][:limit]
    return jsonify(items)

@app.route("/api/articles/new")
def api_articles_new():
    cutoff = time.time() - 120
    with lock:
        recent = [a for a in found_articles
                  if datetime.fromisoformat(a["timestamp"]).timestamp() > cutoff]
    return jsonify(recent)

@app.route("/api/status")
def api_status():
    with lock: total = len(found_articles)
    return jsonify({
        "running": True, "total": total,
        "silver_g": SILVER_G, "gold_g": GOLD_G,
        "roi_min": ROI_MIN, "profit_min": PROFIT_MIN,
        "ebay_api": bool(EBAY_APP_ID and _ebay_token),
        "stats": stats,
    })

@app.route("/health")
def health():
    return jsonify({"status":"ok"}), 200

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

@app.route("/<path:path>")
def static_files(path):
    return send_from_directory(".", path)

if __name__ == "__main__":
    log.info(f"VAULTFLIP | Port:{PORT} | ROI_MIN:{ROI_MIN}% | eBay API:{'OUI' if EBAY_APP_ID else 'NON (HTML fallback)'}")
    threading.Thread(target=scan_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)

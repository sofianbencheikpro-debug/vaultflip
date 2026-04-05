#!/usr/bin/env python3
"""VAULTFLIP — Scraper Production (Railway.app)"""

import os, time, random, re, json, threading, logging
from datetime import datetime, timezone
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
log = logging.getLogger(__name__)

app = Flask(__name__, static_folder='.')
CORS(app)

PORT          = int(os.environ.get('PORT', 5001))
ROI_MIN       = int(os.environ.get('ROI_MIN', 25))
PROFIT_MIN    = int(os.environ.get('PROFIT_MIN', 15))
SCAN_INTERVAL = int(os.environ.get('SCAN_INTERVAL', 40))
SILVER_G      = float(os.environ.get('SILVER_G', 0.93))
GOLD_G        = float(os.environ.get('GOLD_G', 89.24))

UA_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1",
]
def get_headers():
    return {"User-Agent": random.choice(UA_LIST), "Accept-Language": "fr-FR,fr;q=0.9", "Accept": "text/html,*/*;q=0.8", "DNT": "1"}

SEARCH_QUERIES = [
    ("5 francs semeuse argent",       "5 francs semeuse argent 835",      "semeuse",  13,   12,   0.835),
    ("lot semeuse argent 2 francs",   "lot semeuse 2 francs argent",      "semeuse",  70,   50,   0.835),
    ("100 francs hercule argent",     "100 francs hercule argent 900",    "hercule",  40,   15,   0.900),
    ("10 francs hercule argent",      "10 francs hercule argent",         "hercule",  22,   10,   0.900),
    ("lot monnaies argent anciennes", "lot monnaies francs argent",       "franc",    50,   40,   0.835),
    ("5 francs louis philippe argent","5 francs louis philippe argent",   "franc",    85,   25,   0.900),
    ("20 francs napoleon or",         "20 francs napoleon or 900",        "napoleon", 440,  6.45, 0.900),
    ("lingot argent 100g",            "lingot argent 100g umicore",       "lingot",   93,   100,  0.999),
    ("game boy lot jeux",             "game boy lot jeux nintendo",       "jeux",     160,  0,    0),
    ("super nintendo snes lot jeux",  "super nintendo snes jeux lot",     "jeux",     200,  0,    0),
    ("nintendo 64 lot jeux",          "nintendo 64 lot jeux mario",       "jeux",     250,  0,    0),
    ("mega drive lot jeux sega",      "sega mega drive lot jeux sonic",   "jeux",     150,  0,    0),
    ("lot cartes pokemon base set",   "pokemon carte holographique base", "pokemon",  200,  0,    0),
    ("billet 500 francs ancien",      "billet 500 francs moliere 1959",   "billet",   85,   0,    0),
    ("vinyle jazz soul 33t lot",      "vinyle jazz soul 60s lp lot",      "vinyle",   80,   0,    0),
    ("platine thorens vintage",       "platine vinyle thorens garrard",   "vinyle",   280,  0,    0),
    ("tintin edition originale",      "tintin asterix edition originale", "bd",        120,  0,    0),
    ("leica appareil photo argentique","leica m3 m6 argentique",          "vintage",  900,  0,    0),
    ("seiko automatique vintage",     "seiko 5 automatic vintage",        "montre",   180,  0,    0),
    ("omega seamaster vintage",       "omega seamaster automatique",      "montre",   650,  0,    0),
    ("air jordan nike retro",         "nike air jordan 1 retro og",       "sneakers", 500,  0,    0),
    ("morgan dollar argent",          "morgan dollar 1881 argent",        "piece",    45,   26.7, 0.900),
]

found_articles = []
seen_urls      = set()
next_id        = 1000
lock           = threading.Lock()
stats          = {"total_scans": 0, "total_found": 0, "last_scan": None, "errors": 0}


def estimate_value(prix, cat, poids_g, titre_fin):
    metal_val = round(poids_g * SILVER_G * titre_fin, 2) if poids_g > 0 and titre_fin > 0 else 0
    numis = {"semeuse":13,"hercule":38,"franc":25,"napoleon":440,"lingot":max(metal_val,prix*0.95),"piece":42,"jeux":0,"pokemon":0,"billet":80,"vinyle":70,"vintage":350,"bd":120,"montre":300,"sneakers":350}.get(cat, 0)
    return max(metal_val, numis) if (metal_val or numis) else 0


def calc_roi(prix, frais_port, revente_est, frais_vente=5):
    cout = prix + frais_port
    profit = revente_est - frais_vente - cout
    if cout <= 0: return 0, 0
    return round(profit / cout * 100), round(profit, 2)


def age_label(dt_str):
    try:
        dt = datetime.fromisoformat(dt_str.replace('Z','+00:00'))
        diff = int((datetime.now(dt.tzinfo) - dt).total_seconds())
        if diff < 60: return "À l'instant"
        if diff < 3600: return f"il y a {diff//60} min"
        if diff < 86400: return f"il y a {diff//3600}h"
        return f"il y a {diff//86400}j"
    except: return "récemment"


def make_article(titre, prix, frais_port, lien, plateforme, cat, poids_g, titre_fin, img="", ville="", age="récemment"):
    global next_id
    if lien in seen_urls: return None
    val_reelle  = estimate_value(prix, cat, poids_g, titre_fin)
    revente_est = val_reelle * 0.92 if val_reelle > 0 else prix * 1.28
    roi_pct, profit = calc_roi(prix, frais_port, revente_est)
    if roi_pct < ROI_MIN or profit < PROFIT_MIN: return None
    seen_urls.add(lien)
    next_id += 1
    return {
        "id": next_id, "titre": titre, "prix": prix, "fraisPort": round(frais_port,2),
        "valReelle": round(val_reelle,2), "revente": round(revente_est,2),
        "roi": roi_pct, "profit": profit,
        "lien": lien,        # LIEN DIRECT ANNONCE
        "plateforme": plateforme, "ville": ville, "age": age, "cat": cat,
        "image": img, "auth": 88 if plateforme=="lbc" else 82 if plateforme=="ebay" else 80,
        "timestamp": datetime.now(timezone.utc).isoformat(), "hot": roi_pct >= 35,
    }


def scrape_lbc(query, cat, val_ref, poids_g, titre_fin):
    results = []
    try:
        prix_max = int(val_ref * 0.88) if val_ref > 5 else 500
        payload = {"filters":{"keywords":{"text":query},"ranges":{"price":{"min":1,"max":prix_max}}},"sort_by":"time","sort_order":"desc","limit":15,"offset":0}
        headers = {**get_headers(), "Content-Type":"application/json", "api_key":"ba0c2dad52b3565fd3cc99f8f2c3a267"}
        resp = requests.post("https://api.leboncoin.fr/finder/search", json=payload, headers=headers, timeout=12)
        if resp.status_code != 200: return results
        for ad in resp.json().get("ads", []):
            raw = ad.get("price",[0]); prix = (raw[0] if isinstance(raw,list) else raw) or 0
            if prix <= 0: continue
            lien = f"https://www.leboncoin.fr/ad/divers/{ad.get('list_id','')}"
            titre_ad = ad.get("subject","").strip()
            loc = ad.get("location",{}); ville = loc.get("city","") if isinstance(loc,dict) else ""
            ship = ad.get("shipping",{}); has_ship = isinstance(ship,dict) and ship.get("type")!="disabled"
            frais_port = 5.5 if has_ship else 0
            imgs = ad.get("images",{}); img = (imgs.get("urls_large") or imgs.get("urls") or [""])[0] if isinstance(imgs,dict) else ""
            a = make_article(titre_ad, prix, frais_port, lien, "lbc", cat, poids_g, titre_fin, img, ville, age_label(ad.get("first_publication_date","")))
            if a: results.append(a)
    except Exception as e:
        log.warning(f"LBC [{query}]: {e}"); stats["errors"]+=1
    return results


def scrape_ebay(query, cat, val_ref, poids_g, titre_fin):
    results = []
    try:
        prix_max = int(val_ref * 0.86) if val_ref > 5 else 300
        url = f"https://www.ebay.fr/sch/i.html?_nkw={quote_plus(query)}&_sop=10&_udhi={prix_max}&LH_ItemCondition=1000%7C2000%7C2500&LH_PrefLoc=1"
        resp = requests.get(url, headers=get_headers(), timeout=14)
        if resp.status_code != 200: return results
        soup = BeautifulSoup(resp.text, "lxml")
        for item in soup.select(".s-item")[:20]:
            title_el = item.select_one(".s-item__title")
            if not title_el: continue
            titre_ad = title_el.get_text(strip=True)
            if "Shop on eBay" in titre_ad or not titre_ad: continue
            price_el = item.select_one(".s-item__price")
            if not price_el: continue
            try: prix = float(re.sub(r"[^\d,.]","",price_el.get_text(strip=True).split("à")[0]).replace(",","."))
            except: continue
            if prix <= 0: continue
            link_el = item.select_one("a.s-item__link")
            if not link_el or not link_el.get("href"): continue
            lien = link_el["href"].split("?")[0]
            if not lien.startswith("http"): continue
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
            if a: results.append(a)
    except Exception as e:
        log.warning(f"eBay [{query}]: {e}"); stats["errors"]+=1
    return results


def scrape_vinted(query, cat, val_ref):
    results = []
    try:
        prix_max = int(val_ref * 0.84) if val_ref > 5 else 150
        url = f"https://www.vinted.fr/api/v2/catalog/items?search_text={quote_plus(query)}&order=newest_first&price_to={prix_max}&per_page=15"
        resp = requests.get(url, headers=get_headers(), timeout=10)
        if resp.status_code != 200: return results
        for item in resp.json().get("items",[]):
            raw = item.get("price",{}); prix = float(raw.get("amount",0) if isinstance(raw,dict) else raw or 0)
            if prix <= 0: continue
            slug = item.get("url",f"/items/{item.get('id','')}")
            lien = f"https://www.vinted.fr{slug}" if slug.startswith("/") else slug
            titre_ad = item.get("title","").strip()
            svc = item.get("service_fee",{}); frais_port = float(svc.get("amount",3.5) if isinstance(svc,dict) else 3.5)
            photo = item.get("photo",{}); img = (photo.get("full_size_url") or photo.get("url") or "") if isinstance(photo,dict) else ""
            a = make_article(titre_ad, prix, frais_port, lien, "vint", cat, 0, 0, img)
            if a: results.append(a)
    except Exception as e:
        log.warning(f"Vinted [{query}]: {e}"); stats["errors"]+=1
    return results


def update_metal_prices():
    global SILVER_G, GOLD_G
    try:
        resp = requests.get("https://api.metals.live/v1/spot/silver,gold", timeout=8)
        if resp.status_code == 200:
            usd_eur, oz_g = 0.92, 31.1035
            for entry in resp.json():
                if entry.get("silver"): SILVER_G = round(entry["silver"]*usd_eur/oz_g, 4)
                if entry.get("gold"):   GOLD_G   = round(entry["gold"]*usd_eur/oz_g, 4)
            log.info(f"Cours — Ag:{SILVER_G}€/g Au:{GOLD_G}€/g")
    except Exception as e:
        log.debug(f"Cours métaux: {e}")


def scan_loop():
    log.info("Scanner démarré")
    update_metal_prices()
    while True:
        q_lbc, q_ebay, cat, val_ref, poids, titre_fin = random.choice(SEARCH_QUERIES)
        log.info(f"Scan → {q_lbc} [{cat}]")
        stats["last_scan"] = datetime.now(timezone.utc).isoformat()
        stats["total_scans"] += 1
        new_items = []
        lbc = scrape_lbc(q_lbc, cat, val_ref, poids, titre_fin)
        new_items.extend(lbc)
        if lbc: log.info(f"  LBC: {len(lbc)} affaire(s)")
        time.sleep(random.uniform(2.5, 4.5))
        ebay = scrape_ebay(q_ebay, cat, val_ref, poids, titre_fin)
        new_items.extend(ebay)
        if ebay: log.info(f"  eBay: {len(ebay)} affaire(s)")
        time.sleep(random.uniform(2, 4))
        if cat in ["jeux","sneakers","montre","billet","vinyle"]:
            vint = scrape_vinted(q_lbc, cat, val_ref)
            new_items.extend(vint)
            if vint: log.info(f"  Vinted: {len(vint)} affaire(s)")
        with lock:
            for a in new_items: found_articles.insert(0, a)
            del found_articles[300:]
        stats["total_found"] += len(new_items)
        if new_items: log.info(f"  ✓ {len(new_items)} ajoutée(s)")
        if stats["total_scans"] % 10 == 0: update_metal_prices()
        time.sleep(SCAN_INTERVAL + random.uniform(0, 12))


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
        recent = [a for a in found_articles if datetime.fromisoformat(a["timestamp"]).timestamp() > cutoff]
    return jsonify(recent)

@app.route("/api/status")
def api_status():
    with lock: total = len(found_articles)
    return jsonify({"running":True,"total":total,"silver_g":SILVER_G,"gold_g":GOLD_G,"roi_min":ROI_MIN,"profit_min":PROFIT_MIN,"scan_interval":SCAN_INTERVAL,"stats":stats})

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
    log.info(f"VAULTFLIP — Port:{PORT} ROI_MIN:{ROI_MIN}% SCAN:{SCAN_INTERVAL}s")
    threading.Thread(target=scan_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)

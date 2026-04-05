# VAULTFLIP — Guide déploiement Railway

## 5 étapes pour avoir de vraies annonces sur mobile ET PC

### Étape 1 — Crée un compte GitHub (gratuit)
https://github.com/signup

### Étape 2 — Upload les fichiers sur GitHub
1. Nouveau repository → nom : "vaultflip"
2. Upload : index.html, scraper.py, requirements.txt, Procfile, railway.json
3. Commit changes

### Étape 3 — Crée un compte Railway (gratuit puis 5$/mois)
https://railway.app
→ "New Project" → "Deploy from GitHub repo" → sélectionne "vaultflip"
→ Railway détecte automatiquement Python et lance le scraper

### Étape 4 — Génère une URL publique
Dans Railway → Settings → Networking → Generate Domain
Tu obtiens une URL type : https://vaultflip-production.up.railway.app

### Étape 5 — Ouvre sur mobile et PC
Mets l'URL en favori sur ton téléphone.
En bas à droite : 🟢 Scraper actif — vraies annonces

---

## Ce que tu auras

- Site accessible 24h/24 depuis ton mobile ET ton PC
- Scanner LBC + eBay + Vinted toutes les 40 secondes
- Seulement les affaires avec ROI > 25% et profit > 15€
- Liens directs vers les vraies annonces
- Cours or et argent mis à jour automatiquement
- Notifications en temps réel sur le site

## Prix
- Railway Hobby : 5$/mois (~4,60€)
- GitHub : gratuit
- Total : ~5€/mois

## Variables d'environnement Railway (optionnel)
Dans Railway → Variables :
- ROI_MIN=30 (seuil ROI minimum)
- PROFIT_MIN=20 (profit minimum en €)
- SCAN_INTERVAL=40 (secondes entre scans)

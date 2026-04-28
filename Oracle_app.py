import streamlit as st
import pandas as pd
import easyocr
import re
import json
import os
from difflib import get_close_matches
from PIL import Image
import numpy as np
from cerveau_1 import CerveauOracle
from cerveau_2 import CerveauFinancier
from mahita_ia import MahitaIA

oracle_brain = CerveauOracle()    # L'expert Sportif
finance_brain = CerveauFinancier() # L'expert de l'Argent
# Configuration
st.set_page_config(page_title="Oracle Mahita V30", layout="wide")

# --- STYLE CSS : ORACLE MAHITA & NOTIFICATIONS ---
st.markdown("""
    <style>
    .main-header {
        text-align: center;
        padding: 25px;
        border: 5px solid #7FFFD4;
        border-radius: 20px;
        background-color: #0E1117;
        box-shadow: 0px 0px 30px #7FFFD4;
        margin-bottom: 15px;
    }
    .header-title {
        color: #FFFFFF;
        font-size: 3.5em;
        font-weight: 900;
        text-transform: uppercase;
        letter-spacing: 6px;
        margin: 0;
        -webkit-text-stroke: 1.5px #7FFFD4;
        text-shadow: 0px 0px 15px #7FFFD4;
    }
    .prono-safe { border-left: 5px solid #00FF00; padding: 10px; background: rgba(0, 255, 0, 0.1); margin-bottom: 10px; border-radius: 5px; }
    .prono-risque { border-left: 5px solid #FFA500; padding: 10px; background: rgba(255, 165, 0, 0.1); margin-bottom: 10px; border-radius: 5px; }
    .prono-fun { border-left: 5px solid #FF4B4B; padding: 10px; background: rgba(255, 75, 75, 0.1); margin-bottom: 10px; border-radius: 5px; }
    .alerte-oracle { color: #FFD700; font-size: 0.85em; font-style: italic; margin-top: 5px; }
    
    .stSelectbox div[data-baseweb="select"] { border-color: #7FFFD4 !important; }
    .next-day-box { text-align: center; color: #7FFFD4; font-weight: bold; font-size: 1.2em; margin-top: 10px; }
    </style>
    """, unsafe_allow_html=True)

def custom_notify(text):
    msg = f"""<div style="padding: 15px; border: 3px solid #00FF00; border-radius: 10px; background-color: #0E1117; color: #FFFFFF; text-align: center; font-weight: 900; box-shadow: 0px 0px 20px #00FF00; margin: 15px 0px; font-size: 1.3em; text-transform: uppercase; -webkit-text-stroke: 1px #00FF00;">{text}</div>"""
    st.markdown(msg, unsafe_allow_html=True)

# --- HELPERS HISTORIQUE (TRAJECTOIRE / FORME / H2H) ---
def _journees_triees(season_data):
    """Retourne les clés Journée X triées par numéro croissant."""
    keys = [k for k in season_data.keys() if re.search(r'\d+', k)]
    return sorted(keys, key=lambda k: int(re.search(r'\d+', k).group()))

def get_series(season_data, teams_list, n=5):
    """Pour chaque équipe : chaîne 'VVNDV' des n derniers résultats (récent à droite)."""
    series = {t: "" for t in teams_list}
    for jk in _journees_triees(season_data):
        for m in season_data[jk].get("res", []):
            try:
                s_h, s_a = map(int, m['s'].replace('-', ':').split(':'))
                h, a = m['h'], m['a']
                if h in series:
                    series[h] += "V" if s_h > s_a else "N" if s_h == s_a else "D"
                if a in series:
                    series[a] += "V" if s_a > s_h else "N" if s_a == s_h else "D"
            except (ValueError, KeyError, AttributeError):
                continue
    return {t: s[-n:] for t, s in series.items()}

def get_team_form_stats(season_data, teams_list):
    """Calcule moyennes BP/BC à domicile et extérieur pour chaque équipe + moyennes ligue."""
    stats = {t: {"BP_dom":0,"BC_dom":0,"MJ_dom":0,"BP_ext":0,"BC_ext":0,"MJ_ext":0} for t in teams_list}
    total_buts_dom, total_buts_ext, total_matchs = 0, 0, 0
    for jk in _journees_triees(season_data):
        for m in season_data[jk].get("res", []):
            try:
                s_h, s_a = map(int, m['s'].replace('-', ':').split(':'))
                h, a = m['h'], m['a']
                if h in stats and a in stats:
                    stats[h]["BP_dom"] += s_h; stats[h]["BC_dom"] += s_a; stats[h]["MJ_dom"] += 1
                    stats[a]["BP_ext"] += s_a; stats[a]["BC_ext"] += s_h; stats[a]["MJ_ext"] += 1
                    total_buts_dom += s_h; total_buts_ext += s_a; total_matchs += 1
            except (ValueError, KeyError, AttributeError):
                continue
    avg_dom = (total_buts_dom / total_matchs) if total_matchs else 1.4
    avg_ext = (total_buts_ext / total_matchs) if total_matchs else 1.1
    forme = {}
    for t, s in stats.items():
        forme[t] = {
            "buts_marques_dom": (s["BP_dom"]/s["MJ_dom"]) if s["MJ_dom"] else avg_dom,
            "buts_encaisses_dom": (s["BC_dom"]/s["MJ_dom"]) if s["MJ_dom"] else avg_ext,
            "buts_marques_ext": (s["BP_ext"]/s["MJ_ext"]) if s["MJ_ext"] else avg_ext,
            "buts_encaisses_ext": (s["BC_ext"]/s["MJ_ext"]) if s["MJ_ext"] else avg_dom,
            "matchs_joues": s["MJ_dom"] + s["MJ_ext"]
        }
    forme["__ligue__"] = {"avg_dom": avg_dom, "avg_ext": avg_ext, "total_matchs": total_matchs}
    return forme

def get_h2h(season_data, equipe_h, equipe_a, n=3):
    """Retourne la tendance des derniers face-à-face (peu importe qui jouait à domicile)."""
    rencontres = []
    for jk in _journees_triees(season_data):
        for m in season_data[jk].get("res", []):
            try:
                if {m['h'], m['a']} == {equipe_h, equipe_a}:
                    s_h, s_a = map(int, m['s'].replace('-', ':').split(':'))
                    # Normaliser du point de vue de l'équipe domicile actuelle
                    if m['h'] == equipe_h:
                        rencontres.append((s_h, s_a))
                    else:
                        rencontres.append((s_a, s_h))
            except (ValueError, KeyError, AttributeError):
                continue
    return rencontres[-n:] if rencontres else []

# --- CALCUL CLASSEMENT ---
def get_standings(season_data, teams_list):
    stats = {team: {"MJ": 0, "V": 0, "N": 0, "D": 0, "BP": 0, "BC": 0, "Diff": 0, "Pts": 0} for team in teams_list}
    for jk, data in season_data.items():
        if "res" in data and data["res"]:
            for m in data["res"]:
                try:
                    s_h, s_a = map(int, m['s'].replace('-', ':').split(':'))
                    h, a = m['h'], m['a']
                    if h in stats and a in stats:
                        stats[h]["MJ"] += 1; stats[a]["MJ"] += 1
                        stats[h]["BP"] += s_h; stats[h]["BC"] += s_a
                        stats[a]["BP"] += s_a; stats[a]["BC"] += s_h
                        if s_h > s_a: stats[h]["V"] += 1; stats[h]["Pts"] += 3; stats[a]["D"] += 1
                        elif s_h < s_a: stats[a]["V"] += 1; stats[a]["Pts"] += 3; stats[h]["D"] += 1
                        else: stats[h]["N"] += 1; stats[h]["Pts"] += 1; stats[a]["N"] += 1; stats[a]["Pts"] += 1
                except (ValueError, KeyError, AttributeError): continue
    df = pd.DataFrame.from_dict(stats, orient='index').reset_index().rename(columns={'index': 'Équipe'})
    for t in stats: df.loc[df['Équipe'] == t, 'Diff'] = stats[t]['BP'] - stats[t]['BC']
    df = df.sort_values(by=["Pts", "Diff", "BP"], ascending=False).reset_index(drop=True)
    df.insert(0, 'Rang', range(1, len(df) + 1))
    return df

# --- PERSISTENCE ---
DB_FILE = "oracle_history.json"
def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except (json.JSONDecodeError, OSError): return {}
    return {}

def save_db(data):
    with open(DB_FILE, "w", encoding="utf-8") as f: json.dump(data, f, indent=4, ensure_ascii=False)

if 'history' not in st.session_state:
    st.session_state['history'] = load_db()
    if not st.session_state['history']: st.session_state['history']["Saison 2026"] = {}

# --- INITIALISATION DE MAHITA IA ---
MAHITA_FILE = "mahita_journal.json"
def load_mahita():
    if os.path.exists(MAHITA_FILE):
        try:
            with open(MAHITA_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except (json.JSONDecodeError, OSError): return None
    return None

def save_mahita(ia):
    try:
        with open(MAHITA_FILE, "w", encoding="utf-8") as f:
            json.dump(ia.to_dict(), f, indent=2, ensure_ascii=False)
    except OSError:
        pass

if 'mahita' not in st.session_state:
    ia = MahitaIA()
    ia.from_dict(load_mahita())
    st.session_state['mahita'] = ia

# --- ENGINE OCR ---
@st.cache_resource
def load_ocr(): return easyocr.Reader(['en', 'fr'], gpu=False)
reader = load_ocr()

class OracleEngine:
    def __init__(self):
        self.teams_list = ["Leeds", "Brighton", "A. Villa", "Manchester Blue", "C. Palace", "Bournemouth", "Spurs", "Burnley", "West Ham", "Liverpool", "Fulham", "Newcastle", "Manchester Red", "Everton", "London Blues", "Wolverhampton", "Sunderland", "N. Forest", "London Reds", "Brentford"]
    def clean_team(self, text):
        m = get_close_matches(text, self.teams_list, n=1, cutoff=0.3)
        return m[0] if m else None

engine = OracleEngine()

# --- HEADER ---
st.markdown('<div class="main-header"><h1 class="header-title">Oracle Mahita</h1></div>', unsafe_allow_html=True)

col_l, col_m, col_r = st.columns([1, 1, 1])
with col_m:
    saisons = list(st.session_state['history'].keys())
    s_active = st.selectbox("Saison", saisons, label_visibility="collapsed")
    st.session_state['s_active'] = s_active
    
    days = [int(re.search(r'\d+', k).group()) for k in st.session_state['history'][s_active].keys() if st.session_state['history'][s_active][k].get("res")]
    next_j = max(days) + 1 if days else 1
    st.markdown(f'<div class="next-day-box">PROCHAINE ÉTAPE : J-{next_j}</div>', unsafe_allow_html=True)

# --- NAVIGATION ---
tabs = st.tabs([
    "🏆 CLASSEMENT", "📅 CALENDRIER", "🎯 PRONOS", "⚽ RÉSULTATS",
    "📚 HISTORIQUE", "⚙️ GESTION", "📊 PERFORMANCE & RATING", "🤖 MAHITA IA"
])

# --- TAB 0 : CLASSEMENT ---
with tabs[0]:
    current_standings = get_standings(st.session_state['history'][s_active], engine.teams_list)
    st.table(current_standings)

# --- TAB 1 : CALENDRIER ---
with tabs[1]:
    j_cal = st.number_input("Journée", 1, 50, next_j)
    f_cal = st.file_uploader("📸 Sélectionner le Calendrier", type=['jpg','png','jpeg'], key="up_cal")
    
    if f_cal:
        image_bytes = f_cal.getvalue()
        res = reader.readtext(image_bytes, detail=0)
        t_f, o_f = [], []
        for t in res:
            n = engine.clean_team(t); 
            if n: t_f.append(n)
            for val in re.findall(r"\d+[\.,]\d+", t): o_f.append(float(val.replace(',', '.')))
        
        st.session_state['tmp_cal'] = []
        for i in range(10):
            h = t_f[i*2] if len(t_f)>i*2 else "Inconnu"
            a = t_f[i*2+1] if len(t_f)>i*2+1 else "Inconnu"
            o = o_f[i*3:i*3+3]
            st.session_state['tmp_cal'].append({'h': h, 'a': a, 'o': [o[0] if len(o)>0 else 1.0, o[1] if len(o)>1 else 1.0, o[2] if len(o)>2 else 1.0]})

    if 'tmp_cal' in st.session_state:
        with st.form("form_cal"):
            final_c = []
            for i, m in enumerate(st.session_state['tmp_cal']):
                c1, c2, o1, ox, o2 = st.columns([2,2,1,1,1])
                th = c1.selectbox(f"H{i}", engine.teams_list, index=engine.teams_list.index(m['h']) if m['h'] in engine.teams_list else 0)
                ta = c2.selectbox(f"A{i}", engine.teams_list, index=engine.teams_list.index(m['a']) if m['a'] in engine.teams_list else 0)
                final_c.append({'h':th, 'a':ta, 'o':[o1.number_input("C1", value=m['o'][0], key=f"o1_{i}"), ox.number_input("CX", value=m['o'][1], key=f"ox_{i}"), o2.number_input("C2", value=m['o'][2], key=f"o2_{i}")]})
            
            if st.form_submit_button("🔥 VALIDER & ENREGISTRER"):
                jk = f"Journée {j_cal}"
                if jk not in st.session_state['history'][s_active]: st.session_state['history'][s_active][jk] = {"cal":[], "res":[], "pro":[], "rank":[]}
                st.session_state['history'][s_active][jk]["cal"] = final_c
                # Le "pro" est maintenant calculé par le moteur IA
                st.session_state['history'][s_active][jk]["pro"] = [{"m": f"{m['h']} {int((3.0/m['o'][0])+0.4)}:{int((3.0/m['o'][2])+0.1)} {m['a']}", "c": m['o']} for m in final_c]
                st.session_state['current_ready'] = final_c
                st.session_state['current_j_num'] = j_cal # On stocke la journée pour le cerveau
                save_db(st.session_state['history'])
                custom_notify("Calendrier enregistré !")

# --- TAB 2 : PRONOS & TICKETS (CERVEAU 1 + CERVEAU 2 FINANCIER) ---
with tabs[2]:
    if 'current_ready' in st.session_state:
        j_num = st.session_state.get('current_j_num', 1)
        season_data = st.session_state['history'][s_active]
        standings = get_standings(season_data, engine.teams_list)

        # --- CAPITAL UTILISATEUR POUR KELLY ---
        col_cap, _ = st.columns([1, 3])
        with col_cap:
            capital = st.number_input("💰 Capital (FCFA)", min_value=0.0, value=10000.0, step=1000.0, key="capital_kelly")

        # --- DONNÉES HISTORIQUES POUR LE CERVEAU ---
        series = get_series(season_data, engine.teams_list, n=5)
        formes = get_team_form_stats(season_data, engine.teams_list)
        ligue_stats = formes.pop("__ligue__")

        if ligue_stats["total_matchs"] >= 5:
            st.caption(f"🧠 Cerveau alimenté par {ligue_stats['total_matchs']} matchs historiques (poids forme actif)")
        else:
            st.caption(f"⚠️ Seulement {ligue_stats['total_matchs']} match(s) historiques — la cote bookmaker domine.")

        analyses_completes = []  # Pour le Cerveau Financier

        for m in st.session_state['current_ready']:
            # --- 1) CERVEAU 1 : ANALYSE SPORTIVE ---
            r_dom = standings[standings['Équipe'] == m['h']]['Rang'].values[0] if m['h'] in standings['Équipe'].values else 10
            r_ext = standings[standings['Équipe'] == m['a']]['Rang'].values[0] if m['a'] in standings['Équipe'].values else 10

            serie_dom_real = series.get(m['h'], "")
            serie_ext_real = series.get(m['a'], "")
            forme_dom = formes.get(m['h'])
            forme_ext = formes.get(m['a'])
            h2h = get_h2h(season_data, m['h'], m['a'], n=3)

            analyse = oracle_brain.analyser_match(
                equipe_dom=m['h'], equipe_ext=m['a'], cotes=m['o'],
                journee=j_num,
                serie_dom=serie_dom_real or 0,
                serie_ext=serie_ext_real or 0,
                rang_dom=r_dom, rang_ext=r_ext,
                forme_dom=forme_dom, forme_ext=forme_ext,
                h2h=h2h, ligue=ligue_stats
            )

            # --- 2) CERVEAU 2 : ANALYSE FINANCIÈRE (Value Bet) ---
            rentab = finance_brain.evaluer_rentabilite(analyse['score_predit'], m['o'])

            # --- 3) MISE KELLY CONSEILLÉE ---
            mise_kelly = finance_brain.calculer_mise_kelly(
                rentab['probabilite_choix'], rentab['cote_associee'], capital
            )

            # --- AFFICHAGE PAR MATCH ---
            score_txt = analyse['score_predit'].replace(':', ' : ')
            with st.container():
                st.markdown(
                    f"⚽ **{m['h']} {score_txt} {m['a']}** "
                    f"<span style='color:#7FFFD4'>· Forme {m['h']}: {serie_dom_real or '–'} | {m['a']}: {serie_ext_real or '–'}</span>",
                    unsafe_allow_html=True
                )
                cA, cB, cC, cD = st.columns(4)
                cA.metric("Choix Oracle", analyse['choix_expert'])
                cB.metric("Proba score exact", f"{analyse.get('prob_score_exact', 0):.1f}%")
                cC.metric("Value Bet", f"{rentab['value_bet']}", delta=f"Cote {rentab['cote_associee']}")
                cD.metric("Mise Kelly", f"{mise_kelly:.0f} FCFA")
                for alerte in analyse['alertes']:
                    st.markdown(f"<div class='alerte-oracle'>{alerte}</div>", unsafe_allow_html=True)

            # Combinaison C1 + C2 pour le tri en tickets
            analyses_completes.append({
                "match": f"{m['h']} vs {m['a']}",
                "txt": analyse['choix_expert'],
                "score_predit": analyse['score_predit'],
                "alertes": analyse['alertes'],
                "confiance": analyse['confiance'],
                "probabilite_choix": rentab['probabilite_choix'],
                "value_bet": rentab['value_bet'],
                "cote_associee": rentab['cote_associee'],
                "meilleur_choix": rentab['meilleur_choix'],
                "mise_kelly": mise_kelly
            })

        # --- 4) CERVEAU 2 : DISTRIBUTION INTELLIGENTE EN TICKETS ---
        tickets = finance_brain.preparer_tickets(analyses_completes)

        st.divider()
        c1, c2, c3 = st.columns(3)

        def show_ticket(col, title, css_class, data):
            with col:
                st.markdown(f"### {title}")
                if not data:
                    st.write("Pas de match.")
                    return
                total_cote = 1.0
                total_mise = 0.0
                for x in data[:3]:
                    st.markdown(
                        f"""<div class="{css_class}">
                        <b>{x['match']}</b><br>
                        🎯 {x['txt']} <i>(score prédit {x['score_predit']})</i><br>
                        💰 Cote : {x['cote_associee']} | Value : {x['value_bet']}<br>
                        🪙 Mise Kelly : {x['mise_kelly']:.0f} FCFA
                        </div>""",
                        unsafe_allow_html=True
                    )
                    total_cote *= x['cote_associee']
                    total_mise += x['mise_kelly']
                st.info(f"⚡ Cote combinée : **{total_cote:.2f}** | Mise totale : **{total_mise:.0f} FCFA**")

        show_ticket(c1, "🟢 TICKET BANKER", "prono-safe", tickets["BANKER"])
        show_ticket(c2, "🟡 TICKET EXPLOSIF", "prono-risque", tickets["EXPLOSIF"])
        show_ticket(c3, "🔴 TICKET FUN", "prono-fun", tickets["FUN"])

        # --- SAUVEGARDE DES PRONOS ENRICHIS DANS LA DB ---
        st.divider()
        if st.button("💾 ENREGISTRER LES PRONOS DE LA JOURNÉE", key="save_pronos"):
            jk = f"Journée {j_num}"
            if jk not in st.session_state['history'][s_active]:
                st.session_state['history'][s_active][jk] = {"cal": [], "res": [], "pro": [], "rank": []}
            # Format compact pour la rétrocompatibilité avec Performance
            pro_complet = []
            for a in analyses_completes:
                m_text = a['match'].replace(' vs ', f" {a['score_predit']} ")
                pro_complet.append({
                    "m": m_text,
                    "match": a['match'],
                    "choix_expert": a['txt'],
                    "score_predit": a['score_predit'],
                    "confiance": a['confiance'],
                    "probabilite": a['probabilite_choix'],
                    "value_bet": a['value_bet'],
                    "cote_associee": a['cote_associee'],
                    "meilleur_choix": a['meilleur_choix'],
                    "mise_kelly": a['mise_kelly'],
                    "alertes": a['alertes']
                })
            st.session_state['history'][s_active][jk]["pro"] = pro_complet
            save_db(st.session_state['history'])
            custom_notify("Pronos enrichis enregistrés !")
    else:
        st.info("Veuillez d'abord valider un calendrier.")

# --- TAB 3 : RÉSULTATS (MOTEUR V17.7 RESTAURÉ) ---
with tabs[3]:
    j_res = st.number_input("Journée Résultat", 1, 50, 1, key="jres")
    f_res = st.file_uploader("📸 Scan Résultats", type=['jpg','png','jpeg'])
    if f_res:
        img = Image.open(f_res); w, hi = img.size; mid = w/2
        raw = reader.readtext(f_res.getvalue(), detail=1)
        raw.sort(key=lambda x: x[0][0][1])
        # Filtrage et détection des ancres (équipes à gauche)
        tms = [t for t in [{"n": engine.clean_team(txt), "y": b[0][1], "x": (b[0][0]+b[1][0])/2} for (b, txt, p) in raw] if t["n"] and hi*0.12 < t["y"] < hi*0.95]
        ancs = []
        for t in tms:
            if t["x"] < mid and (not ancs or abs(t["y"] - ancs[-1]["y"]) > 45): ancs.append(t)
        
        extracted_matches = []
        for i, a in enumerate(ancs):
            if len(extracted_matches) >= 10: break
            ys, ye = a["y"]-15, (ancs[i+1]["y"]-15 if i+1 < len(ancs) else hi*0.98)
            inf = {"h": a["n"], "a": "Inconnu", "s": "0:0", "hm": "", "am": "", "mt": ""}
            for (bb, tx, p) in raw:
                cy, cx = (bb[0][1]+bb[2][1])/2, (bb[0][0]+bb[1][0])/2
                if ys <= cy <= ye:
                    tn = engine.clean_team(tx)
                    if tn and cx > mid and tn != inf["h"]: inf["a"] = tn
                    elif re.search(r"^\d[:\-]\d$", tx.strip()) and "MT" not in tx.upper(): inf["s"] = tx
                    elif "MT" in tx.upper(): inf["mt"] = tx
                    elif re.search(r"\d+", tx) and not re.search(r"^\d[:\-]\d$", tx):
                        if cx < mid: inf["hm"] += f" {tx}'"
                        else: inf["am"] += f" {tx}'"
            if inf["a"] != "Inconnu": extracted_matches.append(inf)
        
        with st.form("res_val_form"):
            final_res_data = []
            for i, r in enumerate(extracted_matches):
                st.markdown(f"**{r['h']} vs {r['a']}**")
                c1, c2 = st.columns(2)
                fs = c1.text_input("Score Final", r['s'], key=f"rs{i}")
                ms = c2.text_input("Score MT", r['mt'], key=f"rm{i}")
                b1, b2 = st.columns(2)
                bh = b1.text_input("Buteurs Domicile", r['hm'], key=f"rbh{i}")
                ba = b2.text_input("Buteurs Extérieur", r['am'], key=f"rba{i}")
                final_res_data.append({"h":r['h'], "a":r['a'], "s":fs, "mt":ms, "hm":bh, "am":ba})
            
            if st.form_submit_button("✅ ENREGISTRER DANS L'HISTORIQUE"):
                sn, jk = st.session_state['s_active'], f"Journée {j_res}"
                if jk not in st.session_state['history'][sn]: st.session_state['history'][sn][jk] = {"cal":[], "res":[], "pro":[]}
                st.session_state['history'][sn][jk]["res"] = final_res_data
                save_db(st.session_state['history'])
                custom_notify("Résultats enregistrés ! 🤑")


# --- TAB 4 : HISTORIQUE ---
with tabs[4]:
    sorted_j = sorted(st.session_state['history'][s_active].keys(), key=lambda x: int(re.search(r'\d+', x).group()) if re.search(r'\d+', x) else 0)
    for jk in sorted_j:
        with st.expander(f"📅 {jk}"):
            d = st.session_state['history'][s_active][jk]
            h_tabs = st.tabs(["📋 Calendrier", "🎯 Prono", "⚽ Résultat", "📊 Classement"])
            with h_tabs[0]: 
                st.table(d.get("cal", []))
                if d.get("cal") and st.button(f"🔮 Prédire", key=f"sim_{jk}"):
                    st.session_state['current_ready'] = d["cal"]
                    st.session_state['current_j_num'] = int(re.search(r'\d+', jk).group())
                    st.rerun()
            with h_tabs[1]: st.table(d.get("pro", []))
            with h_tabs[2]: st.table(d.get("res", []))
            with h_tabs[3]: 
                if d.get("rank"): st.table(pd.DataFrame(d["rank"]))

# --- TAB 5 : GESTION ---
with tabs[5]:
    ns = st.text_input("Nom de la nouvelle Saison")
    if st.button("➕ Créer la Saison"): 
        if ns: st.session_state['history'][ns] = {}; save_db(st.session_state['history']); st.rerun()
    st.divider()
    if st.session_state['history']:
        st.download_button("📥 EXPORTER BACKUP", data=json.dumps(st.session_state['history'], indent=4), file_name="oracle_backup.json")

# --- TAB 6 : PERFORMANCE & RATING ---
with tabs[6]:
    st.markdown("<div class='main-header'><h1 class='header-title'>📊 RATING & PERFORMANCE</h1></div>", unsafe_allow_html=True)
    stats_perf = oracle_brain.calculer_performance_globale(st.session_state['history'][s_active])
    if stats_perf["total_matchs"] == 0:
        st.info("ℹ️ L'Oracle a besoin de résultats pour calculer son rating.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Matchs", stats_perf["total_matchs"])
        c2.metric("Réussite 1N2", f"{stats_perf['taux_1n2']:.1f}%")
        c3.metric("Scores Exacts", stats_perf["scores_exacts"])
        c4.metric("Points/Match", f"{stats_perf['moyenne_points']:.2f}")
        st.divider()

        rating = stats_perf["rating_general"]
        color = "green" if rating >= 92 else "orange" if rating >= 70 else "red"
        st.progress(rating / 100)
        st.markdown(
            f"**Score Global : <span style='color:{color}; font-size:25px;'>{rating:.1f} / 100</span>** "
            f"(objectif : <b>92</b>)",
            unsafe_allow_html=True
        )

        # --- BARÈME DE PROGRESSION VERS 92% ---
        ecart = 92 - rating
        if ecart > 0:
            st.warning(f"🎯 Il manque **{ecart:.1f} points** pour atteindre l'objectif de 92%.")
        else:
            st.success("🏆 OBJECTIF 92% ATTEINT ! L'Oracle est en mode élite.")

        st.divider()

        # --- AUTO-CALIBRATION + APPRENTISSAGE ---
        col_btn1, col_btn2, col_btn3 = st.columns(3)
        with col_btn1:
            if st.button("🔄 CALIBRER", key="btn_calibration"):
                rapport = oracle_brain.auto_calibrer(st.session_state['history'][s_active])
                if rapport["biais_detecte"]:
                    st.warning(f"⚠️ Biais : {rapport['biais_detecte']}")
                if rapport["ajustements"]:
                    for aj in rapport["ajustements"]:
                        st.write(f"✓ {aj}")
                    custom_notify("Calibration appliquée !")
                else:
                    st.info("ℹ️ Modèle stable.")
        with col_btn2:
            if st.button("🧬 APPRENDRE PROFILS ADN", key="btn_apprendre"):
                rapport = oracle_brain.apprendre_profils(st.session_state['history'][s_active], engine.teams_list)
                st.write(f"**{len(rapport['profils_appris'])} équipes profilées** ({rapport['nb_changements']} changements)")
                if rapport["nb_changements"] > 0:
                    st.code(rapport["rapport"])
                    custom_notify("Profils ADN appris !")
                else:
                    st.info("Profils déjà à jour.")
        with col_btn3:
            run_backtest = st.button("🔬 BACKTEST COMPLET", key="btn_backtest")

        # --- BACKTEST ---
        if run_backtest:
            with st.spinner("Re-prédiction de chaque journée..."):
                helpers_bt = {
                    "get_series": get_series,
                    "get_team_form_stats": get_team_form_stats,
                    "get_h2h": get_h2h,
                    "teams_list": engine.teams_list,
                }
                bt = oracle_brain.backtester(st.session_state['history'][s_active], helpers=helpers_bt)
            if bt["total"] == 0:
                st.warning("Pas assez de données pour un backtest.")
            else:
                bt_color = "green" if bt['rating_global'] >= 92 else "orange" if bt['rating_global'] >= 70 else "red"
                st.markdown(
                    f"### 🎯 Rating BACKTEST : <span style='color:{bt_color}; font-size:24px;'>"
                    f"{bt['rating_global']:.1f} / 100</span>",
                    unsafe_allow_html=True
                )
                bA, bB, bC = st.columns(3)
                bA.metric("Matchs simulés", bt["total"])
                bB.metric("Scores exacts", bt["scores_exacts"])
                bC.metric("Tendance correcte", bt["tendance_1n2"])

                if bt["evolution"]:
                    df_evo = pd.DataFrame(bt["evolution"])
                    df_evo["objectif"] = 92
                    st.line_chart(df_evo.set_index("journee")[["rating_cumule", "objectif"]])

                df_journees = pd.DataFrame(bt["journees"])
                st.dataframe(df_journees, use_container_width=True)

        st.divider()

        # --- DÉTAIL PAR ÉQUIPE (ATTAQUE / DÉFENSE) ---
        st.markdown("### 📈 Forme par équipe (basée sur l'historique)")
        formes = get_team_form_stats(st.session_state['history'][s_active], engine.teams_list)
        formes.pop("__ligue__", None)
        rows = []
        for team in engine.teams_list:
            f = formes.get(team, {})
            if f.get("matchs_joues", 0) == 0:
                continue
            rows.append({
                "Équipe": team,
                "MJ": f["matchs_joues"],
                "BP/m dom": round(f["buts_marques_dom"], 2),
                "BC/m dom": round(f["buts_encaisses_dom"], 2),
                "BP/m ext": round(f["buts_marques_ext"], 2),
                "BC/m ext": round(f["buts_encaisses_ext"], 2),
            })
        if rows:
            df_forme = pd.DataFrame(rows).sort_values("BP/m dom", ascending=False)
            st.dataframe(df_forme, use_container_width=True)
        else:
            st.info("Pas encore assez de données pour les statistiques par équipe.")


# --- TAB 7 : 🤖 MAHITA IA — ASSISTANT CONVERSATIONNEL ---
with tabs[7]:
    st.markdown("<div class='main-header'><h1 class='header-title'>🤖 MAHITA IA</h1></div>", unsafe_allow_html=True)
    st.caption("Votre assistante intelligente. Elle apprend de votre historique et de vos notes.")

    mahita = st.session_state['mahita']

    # Détection automatique de patterns à chaque visite
    nouveaux_patterns = mahita.detecter_patterns({
        "historique": st.session_state['history'][s_active],
        "oracle_brain": oracle_brain,
    })
    if nouveaux_patterns:
        for p in nouveaux_patterns:
            st.success(f"💡 Mahita a remarqué : *{p['texte']}*")
        save_mahita(mahita)

    # --- AFFICHAGE DE L'HISTORIQUE DE CONVERSATION ---
    chat_box = st.container()
    with chat_box:
        if not mahita.chat_history:
            st.info("👋 Bonjour ! Je suis Mahita IA. Posez-moi une question ou tapez *aide* pour découvrir mes capacités.")
        else:
            for msg in mahita.chat_history[-20:]:
                if msg["role"] == "user":
                    st.markdown(f"<div style='background:#1a1a2e; border-left:4px solid #7FFFD4; padding:10px; margin:5px 0; border-radius:5px;'><b>Vous</b> <span style='color:#888; font-size:0.8em'>{msg['ts']}</span><br>{msg['contenu']}</div>", unsafe_allow_html=True)
                else:
                    st.markdown(f"<div style='background:#0E1117; border-left:4px solid #FFD700; padding:10px; margin:5px 0; border-radius:5px;'><b>🤖 Mahita</b> <span style='color:#888; font-size:0.8em'>{msg['ts']}</span><br>{msg['contenu']}</div>", unsafe_allow_html=True)

    st.divider()

    # --- BOUTONS D'ACTIONS RAPIDES ---
    st.markdown("**Actions rapides :**")
    qa1, qa2, qa3, qa4 = st.columns(4)
    quick_q = None
    if qa1.button("🎯 Meilleur prono", key="qa_1"): quick_q = "meilleur prono"
    if qa2.button("📊 Mon bilan", key="qa_2"): quick_q = "mon bilan"
    if qa3.button("⚠️ Alertes", key="qa_3"): quick_q = "alerte"
    if qa4.button("🤖 Apprends", key="qa_4"): quick_q = "apprends"

    # --- ZONE DE SAISIE ---
    with st.form("form_chat", clear_on_submit=True):
        question_text = st.text_input("Tapez votre message...", key="chat_input",
                                      placeholder="Ex: forme de Liverpool, note: les vendredis sont risqués, etc.")
        envoyer = st.form_submit_button("💬 Envoyer")

    question_finale = question_text if envoyer and question_text.strip() else quick_q
    if question_finale:
        contexte = {
            "historique": st.session_state['history'][s_active],
            "teams_list": engine.teams_list,
            "oracle_brain": oracle_brain,
            "finance_brain": finance_brain,
            "current_ready": st.session_state.get("current_ready"),
            "j_num": st.session_state.get("current_j_num", 1),
            "helpers": {
                "get_series": get_series,
                "get_team_form_stats": get_team_form_stats,
                "get_h2h": get_h2h,
                "get_standings": get_standings,
            }
        }
        mahita.repondre(question_finale, contexte)
        save_mahita(mahita)
        st.rerun()

    st.divider()

    # --- VISUALISATION DU JOURNAL ---
    with st.expander(f"📔 Journal d'expérience ({len(mahita.journal_experience)} note(s))"):
        if mahita.journal_experience:
            for entree in reversed(mahita.journal_experience[-30:]):
                st.markdown(f"• *{entree['date']}* — {entree['texte']}")
            if st.button("🗑️ Effacer le journal", key="clear_journal"):
                mahita.journal_experience = []
                save_mahita(mahita)
                st.rerun()
        else:
            st.info("Aucune note. Ajoutez-en avec *note: ...* dans la conversation.")

    with st.expander(f"💡 Observations automatiques ({len(mahita.observations_auto)})"):
        if mahita.observations_auto:
            for obs in reversed(mahita.observations_auto):
                st.markdown(f"• *{obs['date']}* — {obs['texte']}")
        else:
            st.info("Mahita n'a pas encore détecté de pattern remarquable.")

    if st.button("🧹 Effacer la conversation", key="clear_chat"):
        mahita.chat_history = []
        save_mahita(mahita)
        st.rerun()

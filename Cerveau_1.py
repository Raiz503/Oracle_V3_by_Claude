import re
import math

class CerveauOracle:
    def __init__(self):
        # Configuration des seuils (Cerveau 2)
        self.seuil_safe = 1.70
        self.seuil_fun = 3.40

        # ADN des Équipes (Module 3 & 4 du Playbook)
        self.profils = {
            "London Reds": "VERTICAL", "Manchester Blue": "VERTICAL",
            "Liverpool": "EXPLOSIF",
            "Brentford": "GIANT_KILLER",
            "Everton": "LINEAIRE", "A. Villa": "LINEAIRE",
            "Sunderland": "LANTERNE"
        }
        self.big_four = ["London Reds", "Manchester Blue", "Liverpool", "London Blues"]

        # Poids du modèle hybride (cote du bookmaker vs forme historique)
        # Plus la saison avance, plus on fait confiance à la forme.
        self.poids_cote_initial = 0.65
        self.poids_forme_max = 0.55  # Si saison mature, jusqu'à 55% de poids forme

        # Paramètre rho de Dixon-Coles : corrélation négative pour les scores faibles
        # Valeurs typiques en championnat : -0.10 à -0.18
        self.dc_rho = -0.13

    def analyser_match(self, equipe_dom, equipe_ext, cotes, journee, serie_dom, serie_ext, rang_dom, rang_ext,
                       forme_dom=None, forme_ext=None, h2h=None, ligue=None):
        """
        MOTEUR HYBRIDE V2 : Cote bookmaker + Forme historique + Modules Playbook + Poisson.
        Objectif : score exact >92% via convergence multi-signaux.
        """
        # --- SÉCURITÉ ANTI-CRASH ---
        s_dom = str(serie_dom).upper().strip() if (serie_dom and serie_dom != 0) else ""
        s_ext = str(serie_ext).upper().strip() if (serie_ext and serie_ext != 0) else ""

        # --- MODULE 1 : TRAJECTOIRE (Momentum sur 2 derniers) ---
        momentum_dom = self._calculer_momentum(s_dom)
        momentum_ext = self._calculer_momentum(s_ext)

        # --- MODULE 3 : PLAFOND DE VERRE (3V consécutives = -12%) ---
        plafond_dom = 0.88 if "VVV" in s_dom.replace(" ", "") else 1.0
        plafond_ext = 0.88 if "VVV" in s_ext.replace(" ", "") else 1.0

        # --- MODULE 2.A : LOI DU RELÂCHEMENT (-7% post Big-Four) ---
        rel_dom = 0.93 if (s_dom.endswith("V") and any(b.upper() in s_dom for b in self.big_four)) else 1.0
        rel_ext = 0.93 if (s_ext.endswith("V") and any(b.upper() in s_ext for b in self.big_four)) else 1.0

        # --- 1) FORCE BASÉE SUR LA COTE (signal court terme) ---
        force_cote_dom = (3.0 / cotes[0]) * momentum_dom * plafond_dom * rel_dom
        force_cote_ext = (3.0 / cotes[2]) * momentum_ext * plafond_ext * rel_ext

        # --- 2) FORCE BASÉE SUR LA FORME HISTORIQUE (Poisson-style) ---
        # Expected goals via attaque vs défense adverse, normalisés par moyennes ligue
        force_forme_dom, force_forme_ext = self._calculer_force_forme(forme_dom, forme_ext, ligue)

        # --- 3) FUSION HYBRIDE : poids variable selon maturité de la saison ---
        nb_matchs = (ligue or {}).get("total_matchs", 0)
        # Plus on a de matchs joués, plus la forme prend du poids
        poids_forme = min(self.poids_forme_max, nb_matchs / 100.0)
        poids_cote = 1.0 - poids_forme
        force_dom = poids_cote * force_cote_dom + poids_forme * force_forme_dom
        force_ext = poids_cote * force_cote_ext + poids_forme * force_forme_ext

        # --- 4) AJUSTEMENT H2H (face-à-face) ---
        force_dom, force_ext, h2h_alerte = self._appliquer_h2h(h2h, force_dom, force_ext)

        # --- 5) ADN DES ÉQUIPES (Brentford, Sunderland...) ---
        force_dom, force_ext = self._appliquer_adn(equipe_dom, equipe_ext, force_dom, force_ext, rang_dom, rang_ext)

        # --- 6) PRÉDICTION SCORE PAR MODE DE POISSON ---
        score_dom, score_ext, prob_score_exact = self._mode_poisson(force_dom, force_ext)

        # --- ALERTES & CONFIANCE ---
        alertes = []
        if h2h_alerte:
            alertes.append(h2h_alerte)
        confiance = "MEDIUM"

        # MODULE 2.B : MSS (Loi de Survie Critique)
        if journee >= 30:
            if rang_dom >= 17 and cotes[0] > 2.0:
                alertes.append(f"⚠️ MSS : {equipe_dom} joue sa survie !")
                confiance = "RISQUE"
            if rang_ext >= 17 and cotes[2] > 2.0:
                alertes.append(f"⚠️ MSS : {equipe_ext} joue sa survie !")
                confiance = "RISQUE"

        # MODULE 4 : DÉCISION
        choix = f"Nul ou {equipe_dom}" if cotes[0] < cotes[2] else f"Nul ou {equipe_ext}"
        if cotes[0] < self.seuil_safe or cotes[2] < self.seuil_safe:
            confiance = "BANKER (80-95%)"
            choix = f"{equipe_dom} Gagne" if cotes[0] < cotes[2] else f"{equipe_ext} Gagne"
        elif cotes[1] > self.seuil_fun:
            confiance = "FUN (TICKET)"
            choix = "Match Nul"

        # Bonus de confiance si COTE et FORME convergent fortement
        if abs(force_cote_dom - force_forme_dom) < 0.3 and abs(force_cote_ext - force_forme_ext) < 0.3 and nb_matchs >= 20:
            alertes.append("✨ Convergence Cote+Forme (signal renforcé)")
            if "BANKER" in confiance or score_dom != score_ext:
                confiance = "BANKER (80-95%)"

        return {
            "score_predit": f"{score_dom}:{score_ext}",
            "alertes": alertes,
            "confiance": confiance,
            "choix_expert": choix,
            "force_dom": round(force_dom, 2),
            "force_ext": round(force_ext, 2),
            "prob_score_exact": round(prob_score_exact * 100, 1),
            "poids_forme": round(poids_forme, 2)
        }

    def _calculer_momentum(self, serie):
        """Module 1 : Forme sur les 2 derniers matchs (+15% / -15%)"""
        clean = serie.replace(" ", "")
        if len(clean) < 2: return 1.0
        derniers = clean[-2:]
        if derniers == "VV": return 1.15
        if derniers == "DD": return 0.85
        return 1.0

    def _calculer_force_forme(self, forme_dom, forme_ext, ligue):
        """
        Modèle Poisson : λ_dom = avg_BP_dom_ligue * attaque_dom * defense_ext
                         λ_ext = avg_BP_ext_ligue * attaque_ext * defense_dom
        """
        if not forme_dom or not forme_ext or not ligue:
            return 1.4, 1.0  # Valeurs par défaut neutres
        avg_dom_ligue = ligue.get("avg_dom", 1.4)
        avg_ext_ligue = ligue.get("avg_ext", 1.1)
        if avg_dom_ligue <= 0: avg_dom_ligue = 1.4
        if avg_ext_ligue <= 0: avg_ext_ligue = 1.1

        attaque_dom = forme_dom["buts_marques_dom"] / avg_dom_ligue
        defense_ext = forme_ext["buts_encaisses_ext"] / avg_dom_ligue
        attaque_ext = forme_ext["buts_marques_ext"] / avg_ext_ligue
        defense_dom = forme_dom["buts_encaisses_dom"] / avg_ext_ligue

        # Bornes de sécurité (évite des valeurs extrêmes en début de saison)
        attaque_dom = max(0.4, min(2.5, attaque_dom))
        attaque_ext = max(0.4, min(2.5, attaque_ext))
        defense_dom = max(0.4, min(2.5, defense_dom))
        defense_ext = max(0.4, min(2.5, defense_ext))

        lambda_dom = avg_dom_ligue * attaque_dom * defense_ext
        lambda_ext = avg_ext_ligue * attaque_ext * defense_dom
        return lambda_dom, lambda_ext

    def _appliquer_h2h(self, h2h, f_dom, f_ext):
        """Si l'équipe à domicile a écrasé l'adversaire dans les 3 derniers face-à-face : +8%."""
        if not h2h or len(h2h) < 2:
            return f_dom, f_ext, None
        victoires_dom = sum(1 for (a, b) in h2h if a > b)
        victoires_ext = sum(1 for (a, b) in h2h if b > a)
        if victoires_dom >= 2 and victoires_ext == 0:
            return f_dom * 1.08, f_ext * 0.95, f"📈 H2H favorable au domicile ({victoires_dom}V récentes)"
        if victoires_ext >= 2 and victoires_dom == 0:
            return f_dom * 0.95, f_ext * 1.08, f"📉 H2H favorable à l'extérieur ({victoires_ext}V récentes)"
        return f_dom, f_ext, None

    def _mode_poisson(self, lambda_dom, lambda_ext):
        """
        Modèle DIXON-COLES : Poisson avec correction τ pour les scores faibles
        (0-0, 0-1, 1-0, 1-1) qui sont sur-représentés en football réel.
        Retourne (score_dom, score_ext, probabilité_score_exact).
        """
        lambda_dom = max(0.1, lambda_dom)
        lambda_ext = max(0.1, lambda_ext)
        max_goals = 6
        best = (0, 0, 0.0)
        for h in range(max_goals + 1):
            p_h = self._poisson(lambda_dom, h)
            for a in range(max_goals + 1):
                p_a = self._poisson(lambda_ext, a)
                tau = self._tau_dixon_coles(h, a, lambda_dom, lambda_ext)
                p = tau * p_h * p_a
                if p > best[2]:
                    best = (h, a, p)
        return best[0], best[1], best[2]

    def _tau_dixon_coles(self, x, y, lam, mu):
        """
        Fonction de correction τ de Dixon & Coles (1997).
        Augmente la probabilité des scores nuls/serrés et réduit légèrement (1,1).
        """
        rho = self.dc_rho
        if x == 0 and y == 0:
            return 1.0 - lam * mu * rho
        if x == 0 and y == 1:
            return 1.0 + lam * rho
        if x == 1 and y == 0:
            return 1.0 + mu * rho
        if x == 1 and y == 1:
            return 1.0 - rho
        return 1.0

    def probabilites_1n2_dixon_coles(self, lambda_dom, lambda_ext):
        """
        Calcule P(1), P(N), P(2) en sommant sur la grille Dixon-Coles.
        Utile pour le Cerveau Financier et le backtesting.
        """
        lambda_dom = max(0.1, lambda_dom)
        lambda_ext = max(0.1, lambda_ext)
        max_goals = 6
        p_1, p_n, p_2 = 0.0, 0.0, 0.0
        for h in range(max_goals + 1):
            p_h = self._poisson(lambda_dom, h)
            for a in range(max_goals + 1):
                p_a = self._poisson(lambda_ext, a)
                p = self._tau_dixon_coles(h, a, lambda_dom, lambda_ext) * p_h * p_a
                if h > a: p_1 += p
                elif h == a: p_n += p
                else: p_2 += p
        total = p_1 + p_n + p_2
        if total > 0:
            p_1, p_n, p_2 = p_1/total, p_n/total, p_2/total
        return p_1, p_n, p_2

    @staticmethod
    def _poisson(lam, k):
        """P(X = k) pour X ~ Poisson(lam)."""
        if lam <= 0:
            return 1.0 if k == 0 else 0.0
        return (math.exp(-lam) * lam ** k) / math.factorial(k)

    def _appliquer_adn(self, h, a, f_h, f_a, r_h, r_a):
        """Module ADN : Brentford Giant Killer / Sunderland Lanterne"""
        # Loi du 'Giant Killer'
        if self.profils.get(h) == "GIANT_KILLER" and any(b in a for b in self.big_four):
            f_h *= 1.15 
        # Loi 'Lanterne'
        if self.profils.get(a) == "LANTERNE" and r_h < 10:
            f_a *= 0.80
        return f_h, f_a

    def backtester(self, historique_saison, helpers=None):
        """
        Re-prédit chaque journée en n'utilisant QUE les journées précédentes.
        Permet de mesurer le rating réel du moteur sur l'historique.

        helpers (dict) doit fournir :
          - get_series(season_subset, teams_list, n)
          - get_team_form_stats(season_subset, teams_list)
          - get_h2h(season_subset, h, a, n)
          - teams_list
        Si helpers est None, on backtest avec un signal cote-only.
        """
        rapport = {
            "journees": [],
            "rating_global": 0,
            "scores_exacts": 0,
            "tendance_1n2": 0,
            "total": 0,
            "evolution": []  # rating cumulé par journée
        }
        keys = sorted(
            [k for k in historique_saison.keys() if re.search(r'\d+', k)],
            key=lambda k: int(re.search(r'\d+', k).group())
        )
        if not keys:
            return rapport

        cumul_pts, cumul_total = 0, 0
        for i, jk in enumerate(keys):
            data = historique_saison[jk]
            cal = data.get("cal", [])
            res = data.get("res", [])
            if not cal or not res:
                continue
            # Sous-historique = TOUT ce qui précède (pour éviter la fuite de données)
            sous_hist = {kk: historique_saison[kk] for kk in keys[:i]}
            j_num = int(re.search(r'\d+', jk).group())

            # Pré-calcul si helpers fournis
            series = formes = ligue_stats = None
            if helpers:
                series = helpers["get_series"](sous_hist, helpers["teams_list"], 5)
                formes_full = helpers["get_team_form_stats"](sous_hist, helpers["teams_list"])
                ligue_stats = formes_full.pop("__ligue__", None)
                formes = formes_full

            j_pts, j_exacts, j_tend, j_total = 0, 0, 0, 0
            for cal_m, res_m in zip(cal, res):
                if cal_m['h'] != res_m['h'] or cal_m['a'] != res_m['a']:
                    continue
                # On simule la prédiction
                serie_h = series.get(cal_m['h'], "") if series else ""
                serie_a = series.get(cal_m['a'], "") if series else ""
                forme_h = formes.get(cal_m['h']) if formes else None
                forme_a = formes.get(cal_m['a']) if formes else None
                h2h_data = helpers["get_h2h"](sous_hist, cal_m['h'], cal_m['a'], 3) if helpers else None

                pred = self.analyser_match(
                    equipe_dom=cal_m['h'], equipe_ext=cal_m['a'], cotes=cal_m['o'],
                    journee=j_num, serie_dom=serie_h or 0, serie_ext=serie_a or 0,
                    rang_dom=10, rang_ext=10,
                    forme_dom=forme_h, forme_ext=forme_a, h2h=h2h_data, ligue=ligue_stats
                )
                # Comparaison
                try:
                    s_r_h, s_r_a = map(int, res_m['s'].replace('-', ':').split(':'))
                    s_p_h, s_p_a = map(int, pred['score_predit'].split(':'))
                    j_total += 1
                    if s_r_h == s_p_h and s_r_a == s_p_a:
                        j_pts += 3; j_exacts += 1
                    tend_r = 1 if s_r_h > s_r_a else (2 if s_r_a > s_r_h else 0)
                    tend_p = 1 if s_p_h > s_p_a else (2 if s_p_a > s_p_h else 0)
                    if tend_r == tend_p and not (s_r_h == s_p_h and s_r_a == s_p_a):
                        j_pts += 1; j_tend += 1
                    elif tend_r == tend_p and (s_r_h == s_p_h and s_r_a == s_p_a):
                        j_tend += 1  # comptabilisé aussi pour 1N2
                except (ValueError, KeyError, AttributeError):
                    continue

            cumul_pts += j_pts
            cumul_total += j_total
            rapport["journees"].append({
                "journee": jk,
                "matchs": j_total,
                "exacts": j_exacts,
                "tendance_1n2": j_tend,
                "pts": j_pts,
                "rating": (j_pts / (j_total * 3) * 100) if j_total else 0
            })
            rapport["evolution"].append({
                "journee": j_num,
                "rating_cumule": (cumul_pts / (cumul_total * 3) * 100) if cumul_total else 0
            })
            rapport["scores_exacts"] += j_exacts
            rapport["tendance_1n2"] += j_tend
            rapport["total"] += j_total

        rapport["rating_global"] = (cumul_pts / (cumul_total * 3) * 100) if cumul_total else 0
        return rapport

    def apprendre_profils(self, historique_saison, teams_list):
        """
        Apprentissage automatique des profils ADN à partir des résultats.
        Met à jour self.profils en fonction des patterns détectés.

        Profils détectés :
          - GIANT_KILLER : bat les Big-Four au-dessus de la moyenne
          - LANTERNE : perd contre top-10 dans >75% des cas
          - EXPLOSIF : variance des buts marqués élevée (>1.5)
          - LINEAIRE : variance des buts marqués faible (<0.6)
          - VERTICAL : moyenne BP > 1.8 par match
        """
        if not historique_saison:
            return {"profils_appris": {}, "rapport": "Aucun historique disponible."}

        # 1) Collecte des stats par équipe
        stats = {t: {"buts_marques": [], "vs_big4": [], "vs_top10": []} for t in teams_list}

        # On a besoin du classement pour identifier le top-10
        classement_temp = {t: 0 for t in teams_list}
        for jk, data in historique_saison.items():
            for m in data.get("res", []):
                try:
                    s_h, s_a = map(int, m['s'].replace('-', ':').split(':'))
                    if s_h > s_a: classement_temp[m['h']] = classement_temp.get(m['h'], 0) + 3
                    elif s_a > s_h: classement_temp[m['a']] = classement_temp.get(m['a'], 0) + 3
                    else:
                        classement_temp[m['h']] = classement_temp.get(m['h'], 0) + 1
                        classement_temp[m['a']] = classement_temp.get(m['a'], 0) + 1
                except (ValueError, KeyError, AttributeError):
                    continue
        top10 = set(sorted(classement_temp, key=classement_temp.get, reverse=True)[:10])

        # 2) Parcours réel des matchs pour collecter les patterns
        for jk, data in historique_saison.items():
            for m in data.get("res", []):
                try:
                    s_h, s_a = map(int, m['s'].replace('-', ':').split(':'))
                    h, a = m['h'], m['a']
                    if h in stats:
                        stats[h]["buts_marques"].append(s_h)
                        if a in self.big_four:
                            stats[h]["vs_big4"].append(1 if s_h > s_a else 0)
                        if a in top10:
                            stats[h]["vs_top10"].append(1 if s_h < s_a else 0)
                    if a in stats:
                        stats[a]["buts_marques"].append(s_a)
                        if h in self.big_four:
                            stats[a]["vs_big4"].append(1 if s_a > s_h else 0)
                        if h in top10:
                            stats[a]["vs_top10"].append(1 if s_a < s_h else 0)
                except (ValueError, KeyError, AttributeError):
                    continue

        # 3) Inférence des profils
        nouveaux_profils = {}
        rapport_lignes = []
        for t in teams_list:
            s = stats[t]
            buts = s["buts_marques"]
            if len(buts) < 5:
                continue
            moy = sum(buts) / len(buts)
            variance = sum((b - moy) ** 2 for b in buts) / len(buts)

            profil = None
            # GIANT_KILLER : bat Big-4 plus que 30% du temps
            if len(s["vs_big4"]) >= 2 and (sum(s["vs_big4"]) / len(s["vs_big4"])) >= 0.40:
                profil = "GIANT_KILLER"
            # LANTERNE : perd contre top-10 dans >75% des cas
            elif len(s["vs_top10"]) >= 4 and (sum(s["vs_top10"]) / len(s["vs_top10"])) >= 0.75:
                profil = "LANTERNE"
            # VERTICAL : grosse moyenne offensive
            elif moy >= 1.8:
                profil = "VERTICAL"
            # EXPLOSIF : forte variance
            elif variance >= 1.5:
                profil = "EXPLOSIF"
            # LINEAIRE : faible variance
            elif variance <= 0.6:
                profil = "LINEAIRE"

            if profil:
                ancien = self.profils.get(t)
                nouveaux_profils[t] = profil
                if ancien != profil:
                    rapport_lignes.append(f"• {t} : {ancien or '–'} → {profil} (moy={moy:.2f}, var={variance:.2f})")

        # 4) Mise à jour
        self.profils.update(nouveaux_profils)
        return {
            "profils_appris": nouveaux_profils,
            "nb_changements": len(rapport_lignes),
            "rapport": "\n".join(rapport_lignes) if rapport_lignes else "Profils déjà à jour."
        }

    def auto_calibrer(self, historique_saison):
        """
        Analyse la performance passée pour ajuster automatiquement les seuils
        et le poids forme. Retourne un rapport de calibration.
        """
        rapport = {"ajustements": [], "performance_avant": 0, "biais_detecte": None}
        if not historique_saison:
            return rapport

        # Mesurer le biais de prédiction (sur-évaluation domicile / extérieur ?)
        sur_dom, sur_ext, total = 0, 0, 0
        for jk, data in historique_saison.items():
            for r, p in zip(data.get("res", []), data.get("pro", [])):
                try:
                    s_r_h, s_r_a = map(int, r['s'].replace('-', ':').split(':'))
                    sp = p.get('score_predit') or re.search(r"(\d+):(\d+)", p.get('m', '')).group(0)
                    s_p_h, s_p_a = map(int, sp.split(':'))
                    if s_p_h > s_r_h: sur_dom += 1
                    if s_p_a > s_r_a: sur_ext += 1
                    total += 1
                except (ValueError, AttributeError, KeyError):
                    continue

        if total >= 10:
            taux_sur_dom = sur_dom / total
            taux_sur_ext = sur_ext / total
            if taux_sur_dom > 0.55:
                rapport["biais_detecte"] = "Sur-évaluation domicile"
                rapport["ajustements"].append("Réduction de la force domicile de 5% (correction biais)")
            elif taux_sur_ext > 0.55:
                rapport["biais_detecte"] = "Sur-évaluation extérieur"
                rapport["ajustements"].append("Réduction de la force extérieur de 5% (correction biais)")

        # Ajuster les seuils selon le rating actuel
        perf = self.calculer_performance_globale(historique_saison)
        rapport["performance_avant"] = perf["rating_general"]
        if perf["rating_general"] < 60 and perf["total_matchs"] >= 10:
            self.seuil_safe = max(1.50, self.seuil_safe - 0.10)
            rapport["ajustements"].append(f"Seuil BANKER abaissé à {self.seuil_safe} (plus sélectif)")
        elif perf["rating_general"] > 85 and perf["total_matchs"] >= 10:
            self.seuil_safe = min(2.00, self.seuil_safe + 0.05)
            rapport["ajustements"].append(f"Seuil BANKER relevé à {self.seuil_safe} (modèle solide)")

        return rapport

    def calculer_performance_globale(self, historique_saison):
        """Rating de précision millimétré"""
        stats = {"total": 0, "1n2": 0, "exacts": 0, "pts": 0}
        if not historique_saison: return self._vident()

        for jk, data in historique_saison.items():
            res, pro = data.get("res", []), data.get("pro", [])
            for r, p in zip(res, pro):
                stats["total"] += 1
                try:
                    s_r_h, s_r_a = map(int, r['s'].replace('-', ':').split(':'))
                    m = re.search(r"(\d+):(\d+)", p['m'])
                    if not m: continue
                    s_p_h, s_p_a = map(int, m.groups())
                    if s_r_h == s_p_h and s_r_a == s_p_a:
                        stats["exacts"] += 1 ; stats["pts"] += 3
                    tend_r = 1 if s_r_h > s_r_a else 2 if s_r_a > s_r_h else 0
                    tend_p = 1 if s_p_h > s_p_a else 2 if s_p_a > s_p_h else 0
                    if tend_r == tend_p:
                        stats["1n2"] += 1 ; stats["pts"] += 1
                except (ValueError, KeyError, AttributeError): continue

        t = stats["total"] or 1
        return {
            "total_matchs": stats["total"],
            "taux_1n2": (stats["1n2"] / t) * 100,
            "scores_exacts": stats["exacts"],
            "points_oracle": stats["pts"],
            "moyenne_points": stats["pts"] / t,
            "rating_general": min(100, (stats["pts"] / (t * 3)) * 100)
        }

    def _vident(self):
        return {"total_matchs":0, "taux_1n2":0, "scores_exacts":0, "points_oracle":0, "moyenne_points":0, "rating_general":0}

"""
MAHITA IA — Assistant conversationnel local pour Oracle FootVirtuel.

Architecture :
  - Pas de dépendance LLM externe : moteur de règles + recherche par mots-clés.
  - Apprend en lisant l'historique (DB) et le journal d'expérience de l'utilisateur.
  - Conserve une mémoire des préférences et observations dans `journal_experience`.
  - Comprend ~10 intents : forme d'équipe, prono du jour, bilan perso, conseil
    sur un match, ajout de note, statistiques, alerte de pattern, etc.
"""

import re
from datetime import datetime


class MahitaIA:
    def __init__(self):
        # Mémoire persistante (chargée/sauvée via to_dict / from_dict)
        self.journal_experience = []   # liste de notes datées de l'utilisateur
        self.chat_history = []         # historique de la conversation
        self.preferences = {           # préférences détectées
            "ticket_prefere": None,    # BANKER / EXPLOSIF / FUN
            "equipe_favorite": None,
            "capital_habituel": None,
        }
        self.observations_auto = []    # patterns détectés automatiquement

    # ---------------------- PERSISTENCE ----------------------
    def to_dict(self):
        return {
            "journal_experience": self.journal_experience,
            "chat_history": self.chat_history[-50:],  # on garde les 50 derniers échanges
            "preferences": self.preferences,
            "observations_auto": self.observations_auto[-20:],
        }

    def from_dict(self, data):
        if not data:
            return
        self.journal_experience = data.get("journal_experience", [])
        self.chat_history = data.get("chat_history", [])
        self.preferences = data.get("preferences", self.preferences)
        self.observations_auto = data.get("observations_auto", [])

    # ---------------------- API PUBLIQUE ----------------------
    def repondre(self, question, contexte):
        """
        Point d'entrée principal. `contexte` = dict :
          {
            "historique": dict saison,
            "teams_list": list,
            "oracle_brain": CerveauOracle,
            "finance_brain": CerveauFinancier,
            "current_ready": list (matchs prêts),
            "j_num": int,
            "helpers": dict (get_series, get_team_form_stats, get_h2h, get_standings),
          }
        Retourne (reponse_text, action_optionnelle).
        """
        q = question.strip()
        q_low = q.lower()

        # On enregistre la question
        self._ajouter_message("user", q)

        # Détection d'intent
        reponse = None
        if self._match(q_low, ["bonjour", "salut", "hello", "yo", "wesh", "bonsoir"]):
            reponse = self._saluer(contexte)
        elif self._match(q_low, ["aide", "help", "que peux-tu", "que sais-tu", "tu fais quoi"]):
            reponse = self._aide()
        elif self._match(q_low, ["note:", "remarque:", "j'ai remarqué", "je note", "j'observe"]):
            reponse = self._enregistrer_note(q)
        elif self._match(q_low, ["mes notes", "mon journal", "mes observations", "qu'ai-je dit"]):
            reponse = self._lister_notes()
        elif self._match(q_low, ["mon bilan", "comment je joue", "mes perf", "ma performance", "comment ça va pour moi"]):
            reponse = self._bilan_personnel(contexte)
        elif self._match(q_low, ["meilleur prono", "meilleur pari", "meilleur ticket", "value max", "que jouer", "quoi jouer"]):
            reponse = self._meilleur_prono(contexte)
        elif self._match(q_low, ["forme de", "comment va", "comment joue", "stats de", "info sur"]):
            reponse = self._forme_equipe(q, contexte)
        elif self._match(q_low, [" vs ", "contre", "match entre", "predire", "prédire", "que penses-tu de"]):
            reponse = self._analyser_match_demande(q, contexte)
        elif self._match(q_low, ["rating", "score global", "fiabilité", "fiabilite", "objectif"]):
            reponse = self._info_rating(contexte)
        elif self._match(q_low, ["alerte", "danger", "risque", "attention"]):
            reponse = self._lister_alertes(contexte)
        elif self._match(q_low, ["apprends", "apprendre", "calibre", "améliore-toi"]):
            reponse = self._auto_amelioration(contexte)
        elif self._match(q_low, ["merci", "ok", "super", "génial", "parfait"]):
            reponse = "Avec plaisir ! Je suis là pour ça. 🤝"
        else:
            reponse = self._fallback_intelligent(q, contexte)

        self._ajouter_message("mahita", reponse)
        return reponse

    # ---------------------- INTENTS ----------------------
    def _saluer(self, contexte):
        nb_matchs = self._compter_matchs(contexte)
        nom_pref = self.preferences.get("equipe_favorite")
        sal = "Bonjour 👋 Je suis **Mahita IA**, votre assistante prono."
        if nb_matchs > 0:
            sal += f" J'ai en mémoire {nb_matchs} matchs analysés"
            if nom_pref:
                sal += f", et je sais que vous aimez **{nom_pref}**"
            sal += "."
        sal += "\n\nDemandez-moi par exemple : *« meilleur prono aujourd'hui »*, *« forme de Liverpool »*, ou notez vos observations avec *« note: ... »*."
        return sal

    def _aide(self):
        return (
            "📚 **Voici ce que je sais faire :**\n\n"
            "• **« meilleur prono »** → je vous donne le pari le plus rentable de la journée\n"
            "• **« forme de [équipe] »** → stats offensives/défensives détaillées\n"
            "• **« [équipe1] vs [équipe2] »** → pronostic complet d'un match\n"
            "• **« mon bilan »** → votre performance personnelle\n"
            "• **« note: ... »** → j'enregistre votre observation dans le journal\n"
            "• **« mes notes »** → relit toutes vos observations\n"
            "• **« rating »** → où en est l'Oracle vis-à-vis des 92%\n"
            "• **« apprends »** → je lance la calibration et l'apprentissage des profils\n"
            "• **« alerte »** → matchs à risque MSS / pièges détectés"
        )

    def _enregistrer_note(self, texte_brut):
        # Nettoyer le préfixe
        clean = re.sub(r"^(note\s*:|remarque\s*:|j'ai remarqué|je note|j'observe)\s*", "",
                       texte_brut, flags=re.IGNORECASE).strip()
        if not clean:
            return "Précisez votre note après le mot-clé. Exemple : *note: Liverpool joue mal le mardi*."
        entree = {
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "texte": clean
        }
        self.journal_experience.append(entree)
        # Détection automatique de préférences
        for ticket in ("BANKER", "EXPLOSIF", "FUN"):
            if ticket.lower() in clean.lower():
                self.preferences["ticket_prefere"] = ticket
        return f"📝 Note enregistrée ({len(self.journal_experience)} au total). Je m'en souviendrai."

    def _lister_notes(self):
        if not self.journal_experience:
            return "Votre journal est vide. Ajoutez une observation avec *note: ...*"
        n = len(self.journal_experience)
        derniere_5 = self.journal_experience[-5:]
        lignes = [f"📔 **Journal — {n} note(s) au total**\n"]
        for e in reversed(derniere_5):
            lignes.append(f"• *{e['date']}* — {e['texte']}")
        if n > 5:
            lignes.append(f"\n... (+ {n-5} notes plus anciennes)")
        return "\n".join(lignes)

    def _bilan_personnel(self, contexte):
        oracle = contexte["oracle_brain"]
        hist = contexte["historique"]
        stats = oracle.calculer_performance_globale(hist)
        if stats["total_matchs"] == 0:
            return "Pas encore assez de matchs joués pour un bilan. Enregistrez des résultats d'abord."
        rating = stats["rating_general"]
        ecart_92 = 92 - rating
        msg = (
            f"📊 **Votre bilan actuel :**\n"
            f"• Matchs analysés : **{stats['total_matchs']}**\n"
            f"• Tendance 1N2 correcte : **{stats['taux_1n2']:.1f}%**\n"
            f"• Scores exacts : **{stats['scores_exacts']}**\n"
            f"• Rating Oracle : **{rating:.1f} / 100**\n\n"
        )
        if ecart_92 > 0:
            msg += f"🎯 Il vous manque **{ecart_92:.1f} points** pour atteindre l'objectif **92%**."
            if rating < 60:
                msg += "\n💡 Conseil : utilisez `apprends` pour calibrer le moteur."
            elif rating < 80:
                msg += "\n💡 Vous progressez bien. Concentrez-vous sur les TICKETS BANKER (haute confiance)."
        else:
            msg += "🏆 **OBJECTIF 92% ATTEINT !** L'Oracle est en mode élite."
        return msg

    def _meilleur_prono(self, contexte):
        ready = contexte.get("current_ready") or []
        if not ready:
            return "Aucun calendrier validé. Allez dans l'onglet **CALENDRIER** d'abord."
        finance = contexte["finance_brain"]
        oracle = contexte["oracle_brain"]
        helpers = contexte["helpers"]
        hist = contexte["historique"]
        teams = contexte["teams_list"]
        j_num = contexte.get("j_num", 1)

        series = helpers["get_series"](hist, teams, 5)
        formes_full = helpers["get_team_form_stats"](hist, teams)
        ligue_stats = formes_full.pop("__ligue__", None)

        meilleur = None
        for m in ready:
            forme_h = formes_full.get(m['h'])
            forme_a = formes_full.get(m['a'])
            h2h = helpers["get_h2h"](hist, m['h'], m['a'], 3)
            an = oracle.analyser_match(
                equipe_dom=m['h'], equipe_ext=m['a'], cotes=m['o'], journee=j_num,
                serie_dom=series.get(m['h'], "") or 0, serie_ext=series.get(m['a'], "") or 0,
                rang_dom=10, rang_ext=10,
                forme_dom=forme_h, forme_ext=forme_a, h2h=h2h, ligue=ligue_stats
            )
            rentab = finance.evaluer_rentabilite(an['score_predit'], m['o'])
            if meilleur is None or rentab["value_bet"] > meilleur["value"]:
                meilleur = {
                    "match": f"{m['h']} vs {m['a']}",
                    "score": an['score_predit'],
                    "choix": an['choix_expert'],
                    "value": rentab["value_bet"],
                    "cote": rentab["cote_associee"],
                    "proba": rentab["probabilite_choix"],
                    "confiance": an['confiance']
                }
        if not meilleur:
            return "Pas assez de données pour évaluer."
        return (
            f"🎯 **Meilleur pari de la journée :**\n\n"
            f"⚽ **{meilleur['match']}** — score prédit **{meilleur['score']}**\n"
            f"• Choix : **{meilleur['choix']}**\n"
            f"• Cote : **{meilleur['cote']}** | Probabilité : **{meilleur['proba']}%**\n"
            f"• Value Bet : **{meilleur['value']}** (>1.0 = rentable)\n"
            f"• Confiance : **{meilleur['confiance']}**"
        )

    def _forme_equipe(self, question, contexte):
        equipe = self._extraire_equipe(question, contexte["teams_list"])
        if not equipe:
            return "Je n'ai pas reconnu l'équipe. Essayez : *forme de Liverpool*."
        helpers = contexte["helpers"]
        formes = helpers["get_team_form_stats"](contexte["historique"], contexte["teams_list"])
        formes.pop("__ligue__", None)
        f = formes.get(equipe, {})
        if f.get("matchs_joues", 0) == 0:
            return f"Pas encore de données pour **{equipe}**."
        series = helpers["get_series"](contexte["historique"], contexte["teams_list"], 5)
        s = series.get(equipe, "–")
        # Mémoriser comme équipe favorite si demandée plusieurs fois
        self.preferences["equipe_favorite"] = equipe
        return (
            f"📊 **Forme de {equipe}** ({f['matchs_joues']} matchs)\n\n"
            f"• 🏠 À domicile : **{f['buts_marques_dom']:.2f}** buts marqués / **{f['buts_encaisses_dom']:.2f}** encaissés\n"
            f"• ✈️ À l'extérieur : **{f['buts_marques_ext']:.2f}** buts marqués / **{f['buts_encaisses_ext']:.2f}** encaissés\n"
            f"• 🔥 5 derniers matchs : **{s or '–'}**"
        )

    def _analyser_match_demande(self, question, contexte):
        teams = contexte["teams_list"]
        equipes_trouvees = []
        for t in teams:
            if t.lower() in question.lower():
                equipes_trouvees.append(t)
        if len(equipes_trouvees) < 2:
            return ("Je n'ai pas trouvé deux équipes dans votre question.\n"
                    "Exemple : *que penses-tu de Liverpool vs Brentford ?*")
        h, a = equipes_trouvees[0], equipes_trouvees[1]
        # Cherche le match dans current_ready si présent (sinon analyse théorique)
        ready = contexte.get("current_ready") or []
        match = next((m for m in ready if m['h'] == h and m['a'] == a), None)
        if not match:
            match = next((m for m in ready if {m['h'], m['a']} == {h, a}), None)
        if not match:
            return f"Match **{h} vs {a}** non programmé. Validez le calendrier d'abord."

        oracle = contexte["oracle_brain"]
        helpers = contexte["helpers"]
        hist = contexte["historique"]
        series = helpers["get_series"](hist, teams, 5)
        formes_full = helpers["get_team_form_stats"](hist, teams)
        ligue_stats = formes_full.pop("__ligue__", None)
        h2h = helpers["get_h2h"](hist, match['h'], match['a'], 3)

        an = oracle.analyser_match(
            equipe_dom=match['h'], equipe_ext=match['a'], cotes=match['o'],
            journee=contexte.get("j_num", 1),
            serie_dom=series.get(match['h'], "") or 0,
            serie_ext=series.get(match['a'], "") or 0,
            rang_dom=10, rang_ext=10,
            forme_dom=formes_full.get(match['h']), forme_ext=formes_full.get(match['a']),
            h2h=h2h, ligue=ligue_stats
        )
        # Probas 1N2 Dixon-Coles complètes
        p1, pn, p2 = oracle.probabilites_1n2_dixon_coles(
            an["force_dom"], an["force_ext"]
        )
        msg = (
            f"🔮 **Analyse {match['h']} vs {match['a']}**\n\n"
            f"• Score prédit : **{an['score_predit']}** (proba {an['prob_score_exact']:.1f}%)\n"
            f"• Choix expert : **{an['choix_expert']}**\n"
            f"• Confiance : **{an['confiance']}**\n\n"
            f"📈 **Probabilités 1N2 (Dixon-Coles) :**\n"
            f"• 1 (domicile) : **{p1*100:.1f}%**\n"
            f"• N (nul) : **{pn*100:.1f}%**\n"
            f"• 2 (extérieur) : **{p2*100:.1f}%**"
        )
        if an["alertes"]:
            msg += "\n\n⚠️ **Alertes :**\n" + "\n".join(f"• {a}" for a in an["alertes"])
        if h2h:
            msg += f"\n\n📜 **3 derniers H2H :** {', '.join(f'{x}-{y}' for (x, y) in h2h)}"
        return msg

    def _info_rating(self, contexte):
        stats = contexte["oracle_brain"].calculer_performance_globale(contexte["historique"])
        if stats["total_matchs"] == 0:
            return "Pas encore de rating (aucun résultat enregistré)."
        r = stats["rating_general"]
        ecart = 92 - r
        return (
            f"📈 **Rating actuel : {r:.1f} / 100**\n"
            f"• Objectif : 92.0\n"
            f"• Écart : {'+' if ecart < 0 else '-'}{abs(ecart):.1f} pts\n"
            f"• Matchs : {stats['total_matchs']}\n"
            f"• Scores exacts : {stats['scores_exacts']}"
        )

    def _lister_alertes(self, contexte):
        ready = contexte.get("current_ready") or []
        j_num = contexte.get("j_num", 1)
        if j_num < 30:
            return "Aucune alerte MSS active (la Loi de Survie ne s'applique qu'à partir de la J30)."
        oracle = contexte["oracle_brain"]
        helpers = contexte["helpers"]
        hist = contexte["historique"]
        teams = contexte["teams_list"]
        series = helpers["get_series"](hist, teams, 5)
        formes_full = helpers["get_team_form_stats"](hist, teams)
        ligue_stats = formes_full.pop("__ligue__", None)
        alertes_total = []
        for m in ready:
            an = oracle.analyser_match(
                equipe_dom=m['h'], equipe_ext=m['a'], cotes=m['o'], journee=j_num,
                serie_dom=series.get(m['h'], "") or 0, serie_ext=series.get(m['a'], "") or 0,
                rang_dom=10, rang_ext=10,
                forme_dom=formes_full.get(m['h']), forme_ext=formes_full.get(m['a']),
                h2h=helpers["get_h2h"](hist, m['h'], m['a'], 3),
                ligue=ligue_stats
            )
            if an["alertes"]:
                alertes_total.append(f"• **{m['h']} vs {m['a']}** : {' / '.join(an['alertes'])}")
        if not alertes_total:
            return "✅ Aucune alerte. Journée propre."
        return "⚠️ **Alertes de la journée :**\n\n" + "\n".join(alertes_total)

    def _auto_amelioration(self, contexte):
        oracle = contexte["oracle_brain"]
        hist = contexte["historique"]
        teams = contexte["teams_list"]
        # Apprentissage profils
        rapport_adn = oracle.apprendre_profils(hist, teams)
        # Calibration
        rapport_cal = oracle.auto_calibrer(hist)
        msg = "🤖 **Auto-amélioration lancée :**\n\n"
        msg += f"• Profils ADN appris : **{len(rapport_adn['profils_appris'])}** équipes\n"
        if rapport_adn["nb_changements"] > 0:
            msg += f"• Changements : {rapport_adn['nb_changements']}\n```\n{rapport_adn['rapport']}\n```\n"
        if rapport_cal["ajustements"]:
            msg += "\n• Calibration :\n" + "\n".join(f"  - {a}" for a in rapport_cal["ajustements"])
        if rapport_cal["biais_detecte"]:
            msg += f"\n• ⚠️ Biais : {rapport_cal['biais_detecte']}"
        if rapport_adn["nb_changements"] == 0 and not rapport_cal["ajustements"]:
            msg += "\nLe modèle est déjà bien calibré. 👌"
        return msg

    def _fallback_intelligent(self, question, contexte):
        # Rechercher si la question contient un nom d'équipe
        equipe = self._extraire_equipe(question, contexte["teams_list"])
        if equipe:
            return self._forme_equipe(f"forme de {equipe}", contexte)
        suggestions = [
            "Je ne suis pas sûre d'avoir compris. Essayez :",
            "• *« meilleur prono »*",
            "• *« forme de Liverpool »*",
            "• *« mon bilan »*",
            "• *« note: ... »* pour ajouter une observation",
            "• *« aide »* pour la liste complète"
        ]
        return "\n".join(suggestions)

    # ---------------------- OBSERVATIONS AUTOMATIQUES ----------------------
    def detecter_patterns(self, contexte):
        """À appeler périodiquement. Détecte des patterns et les stocke."""
        hist = contexte["historique"]
        oracle = contexte["oracle_brain"]
        stats = oracle.calculer_performance_globale(hist)
        nouveaux = []
        if stats["total_matchs"] >= 10:
            r = stats["rating_general"]
            if r >= 92 and not any("élite" in o["texte"] for o in self.observations_auto):
                nouveaux.append({"date": datetime.now().strftime("%Y-%m-%d"),
                                 "texte": f"Mode élite débloqué (rating {r:.1f}%) 🏆"})
            if stats["scores_exacts"] >= 5 and not any("scores exacts" in o["texte"] for o in self.observations_auto):
                nouveaux.append({"date": datetime.now().strftime("%Y-%m-%d"),
                                 "texte": f"{stats['scores_exacts']} scores exacts trouvés !"})
        self.observations_auto.extend(nouveaux)
        return nouveaux

    # ---------------------- UTILS ----------------------
    @staticmethod
    def _match(texte, mots):
        return any(m in texte for m in mots)

    @staticmethod
    def _extraire_equipe(texte, teams_list):
        # Recherche exacte d'abord (insensible casse), puis partielle
        t_low = texte.lower()
        for team in sorted(teams_list, key=len, reverse=True):
            if team.lower() in t_low:
                return team
        return None

    def _ajouter_message(self, role, contenu):
        self.chat_history.append({
            "role": role,
            "contenu": contenu,
            "ts": datetime.now().strftime("%H:%M")
        })

    @staticmethod
    def _compter_matchs(contexte):
        total = 0
        for jk, data in contexte["historique"].items():
            total += len(data.get("res", []))
        return total

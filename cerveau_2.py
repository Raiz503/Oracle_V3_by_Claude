class CerveauFinancier:
    def __init__(self):
        # --- PARAMÈTRES FINANCIERS ---
        self.seuil_value = 1.05  # Avantage mathématique minimum (5%) sur le bookmaker
        self.seuil_safe = 1.80   # Cote maximum tolérée pour un ticket "Banker"
        self.seuil_fun = 3.00    # Cote minimum pour tenter un ticket "Fun"

    def evaluer_rentabilite(self, score_predit, cotes):
        """
        Calcule les probabilités à partir du score prédit par le Cerveau 1, 
        puis détecte si le bookmaker a fait une erreur (Value Bet).
        """
        # Extraction des scores du texte "X:Y" du Cerveau 1
        try:
            s_dom, s_ext = map(int, score_predit.split(':'))
        except (ValueError, AttributeError):
            s_dom, s_ext = 1, 1

        # Transformation rudimentaire des scores en probabilités (Base 100%)
        total_buts = s_dom + s_ext + 1 # +1 pour lisser le risque de nul
        prob_dom = min(0.90, max(0.10, s_dom / total_buts))
        prob_ext = min(0.90, max(0.10, s_ext / total_buts))
        prob_nul = max(0.05, 1.0 - (prob_dom + prob_ext))

        # Calcul de la "Value" (Probabilité Oracle x Cote Bookmaker)
        # Si > 1.0, c'est mathématiquement rentable sur le long terme.
        value_dom = prob_dom * cotes[0]
        value_nul = prob_nul * cotes[1]
        value_ext = prob_ext * cotes[2]

        # On isole l'option la plus rentable
        valeurs = {"1": value_dom, "N": value_nul, "2": value_ext}
        meilleur_choix = max(valeurs, key=valeurs.get)
        max_value = valeurs[meilleur_choix]

        return {
            "meilleur_choix": meilleur_choix,
            "probabilite_choix": round((prob_dom if meilleur_choix == "1" else prob_ext if meilleur_choix == "2" else prob_nul) * 100, 1),
            "value_bet": round(max_value, 2),
            "cote_associee": cotes[0] if meilleur_choix == "1" else cotes[2] if meilleur_choix == "2" else cotes[1]
        }

    def preparer_tickets(self, analyses_completes):
        """
        L'Architecte : Trie les matchs de la journée dans 3 tickets selon le risque.
        (Prend en entrée une liste de dictionnaires combinant les résultats C1 + C2)
        """
        tickets = {"BANKER": [], "EXPLOSIF": [], "FUN": []}

        for match in analyses_completes:
            prob = match.get('probabilite_choix', 0)
            val = match.get('value_bet', 0)
            cote = match.get('cote_associee', 1.0)
            alertes = match.get('alertes', [])

            # 1. TICKET BANKER : Très haute proba, pas d'alerte MSS, cote sécurisée
            if prob >= 70 and cote <= self.seuil_safe and not alertes:
                tickets["BANKER"].append(match)
            
            # 2. TICKET EXPLOSIF : Recherche l'erreur de cote du bookmaker (Value Bet)
            elif val >= self.seuil_value:
                tickets["EXPLOSIF"].append(match)
            
            # 3. TICKET FUN : Matchs imprévisibles (Alertes MSS) ou Grosses cotes
            elif cote >= self.seuil_fun or alertes:
                tickets["FUN"].append(match)

        return tickets

    def calculer_mise_kelly(self, probabilite_pct, cote, capital_actuel):
        """
        Loi de Kelly Fractionnelle (Sécurité) : 
        Calcule exactement combien d'argent miser sur un match pour ne jamais faire faillite.
        """
        p = probabilite_pct / 100.0  # Probabilité de gagner
        q = 1.0 - p                  # Probabilité de perdre
        b = cote - 1.0               # Bénéfice net

        if b <= 0: return 0.0

        # Formule de Kelly classique
        kelly_pct = ((b * p) - q) / b
        
        if kelly_pct <= 0:
            return 0.0 # Le pari n'est pas rentable, on ne mise rien.
        
        # Quarter Kelly (On divise par 4 pour éviter une trop grosse variance/banqueroute)
        mise_conseillee = capital_actuel * (kelly_pct * 0.25)
        
        return round(mise_conseillee, 2)

"""Assistant analytique : calculs locaux, visualisations, Gemini optionnel et résilient."""
import json
import re
import time
import unicodedata
import pandas as pd
import plotly.express as px
import streamlit as st

METRICS = {"prix": "prix_nuit", "revenu": "estimated_revenue_l365d", "occupation": "estimated_occupancy_l365d", "note": "review_scores_rating", "annonces": None}
GROUPS = {"quartier": "quartier", "type": "room_type", "global": None}

def _aggregate(frame, metric, group):
    col, by = METRICS[metric], GROUPS[group]
    if frame.empty: return {"erreur": "Aucune annonce ne correspond aux filtres actifs."}
    if col and col not in frame: return {"erreur": f"Colonne {col} indisponible."}
    if by and by not in frame: return {"erreur": f"Colonne {by} indisponible."}
    d = frame[[by, col] if by and col else [by] if by else [col] if col else []].copy() if (by or col) else frame
    if col:
        d[col] = pd.to_numeric(d[col], errors="coerce")
        d = d.dropna(subset=[col])
        if metric in ("prix", "revenu"): d = d[d[col] > 0]
    if by: d = d.dropna(subset=[by])
    if d.empty: return {"erreur": "Aucune valeur exploitable."}
    if by:
        if col:
            out = d.groupby(by, observed=True)[col].agg(["mean", "median", "count"]).reset_index().sort_values("median", ascending=False).head(20)
        else:
            out = d.groupby(by, observed=True).size().reset_index(name="count").sort_values("count", ascending=False).head(20)
        rows = out.to_dict("records")
    else:
        rows = [{"count": len(d), "mean": d[col].mean(), "median": d[col].median()}] if col else [{"count": len(d)}]
    rows = json.loads(json.dumps(rows, default=lambda x: x.item() if hasattr(x, "item") else str(x)))
    for row in rows:
        for k, v in row.items():
            if isinstance(v, float): row[k] = round(v, 2)
    return {"mesure": metric, "regroupement": group, "effectif_valide": len(d), "resultats": rows}

def _review_counts(frame, loader):
    if not {"id_annonce", "room_type"}.issubset(frame.columns): return {"erreur": "Identifiants ou types de logement absents."}
    try: reviews = loader()
    except Exception as exc: return {"erreur": f"Lecture des avis impossible : {type(exc).__name__}"}
    if not {"listing_id", "date"}.issubset(reviews.columns): return {"erreur": "Colonnes des avis absentes."}
    listings = frame[["id_annonce", "room_type"]].drop_duplicates("id_annonce").copy()
    listings["id_annonce"] = pd.to_numeric(listings.id_annonce, errors="coerce")
    r = reviews[["listing_id", "date"]].copy()
    r["listing_id"] = pd.to_numeric(r.listing_id, errors="coerce")
    r["date"] = pd.to_datetime(r.date, errors="coerce")
    joined = r.merge(listings, left_on="listing_id", right_on="id_annonce", how="inner").dropna(subset=["date", "room_type"])
    if joined.empty: return {"erreur": "Aucun avis daté pour les filtres actifs."}
    joined["annee"] = joined.date.dt.year.astype(int)
    cross = pd.crosstab(joined.annee, joined.room_type).sort_index()
    table = cross.reset_index().to_dict("records")
    return {"analyse": "avis_type_annee", "total_avis": len(joined), "logements_avec_avis": int(joined.listing_id.nunique()), "tableau": table, "par_type": {str(k): int(v) for k,v in joined.groupby("room_type").size().items()}, "par_annee": {str(k): int(v) for k,v in joined.groupby("annee").size().items()}}

def _norm(s):
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c))

def _select(question):
    q = _norm(question)
    if any(x in q for x in ("surface", "m2", "historique des prix", "evolution des prix")):
        return [("unsupported", None, None)]
    reviews = any(x in q for x in ("avis", "commentaire", "reviews")) and any(x in q for x in ("combien", "nombre", "annee", "type", "volume", "repartition", "evolution"))
    ratings = any(x in q for x in ("note", "notes", "evaluation", "mieux notes"))
    ops = []
    if ratings: ops.append(("aggregate", "note", "type" if "type" in q or "logement" in q else "quartier" if "quartier" in q else "global"))
    if reviews: ops.append(("reviews", None, None))
    if ops: return ops
    metric = "revenu" if "revenu" in q else "occupation" if "occupation" in q else "annonces" if "annonce" in q and "prix" not in q else "prix"
    group = "quartier" if any(x in q for x in ("quartier", "arrondissement")) else "type" if any(x in q for x in ("type", "logement", "chambre")) else "global"
    return [("aggregate", metric, group)]

def _local_text(results):
    parts = []
    for r in results:
        if "erreur" in r:
            parts.append(r["erreur"]); continue
        if r.get("analyse") == "avis_type_annee":
            parts.append(f"**{r['total_avis']:,} avis datés** pour **{r['logements_avec_avis']:,} logements**. Le tableau ci-dessous croise les années et les types de logements.")
            continue
        parts.append(f"**{r['mesure']} par {r['regroupement']}** — {r['effectif_valide']:,} observations exploitables.")
        for row in r["resultats"][:12]:
            name = row.get("room_type", row.get("quartier", "Ensemble"))
            if "median" in row: parts.append(f"- {name} : médiane **{row['median']}**, moyenne {row['mean']} (n={row['count']})")
            else: parts.append(f"- {name} : {row['count']} annonces")
    return "\n\n".join(parts)

def _visuals(results):
    for r in results:
        if r.get("analyse") == "avis_type_annee":
            d = pd.DataFrame(r["tableau"])
            if d.empty: continue
            st.markdown("**Nombre d'avis par type de logement et par année**")
            st.dataframe(d, hide_index=True, use_container_width=True)
            melted = d.melt(id_vars="annee", var_name="Type de logement", value_name="Avis")
            fig = px.bar(melted, x="annee", y="Avis", color="Type de logement", barmode="stack", color_discrete_map={"Entire home/apt":"#2878D0", "Private room":"#F28C38", "Hotel room":"#13A89E", "Shared room":"#9456CC"})
            fig.update_layout(margin=dict(l=0,r=0,t=10,b=0), xaxis=dict(dtick=1), legend_title_text="Type de logement")
            st.plotly_chart(fig, use_container_width=True)
        elif "resultats" in r and r["regroupement"] != "global":
            st.dataframe(pd.DataFrame(r["resultats"]), hide_index=True, use_container_width=True)

def _available_models(client, preferred):
    """Ne pas supposer qu'un nom de modèle est disponible pour cette clé."""
    try:
        available = []
        for item in client.models.list():
            name = str(getattr(item, "name", "")).removeprefix("models/")
            methods = getattr(item, "supported_actions", None) or getattr(item, "supported_generation_methods", None)
            if name.startswith("gemini-") and (not methods or "generateContent" in methods or "generate_content" in methods):
                available.append(name)
        candidates = [preferred, "gemini-3-flash-preview", "gemini-2.5-flash", "gemini-2.0-flash"]
        return [x for x in dict.fromkeys(candidates + available) if x in available][:4]
    except Exception:
        return [preferred]  # Erreur de découverte : essayer seulement le modèle configuré.

def _call_gemini(key, preferred, question, results):
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=12000))
    models = _available_models(client, preferred)
    if not models: return None, "Aucun modèle compatible n'a été trouvé pour cette clé."
    prompt = ("Tu es analyste de locations courte durée à Lyon. Réponds en français en 120 mots maximum. "
              "N'invente aucun chiffre. Utilise exclusivement les données JSON. "
              "Les revenus et l'occupation sont estimés. Signale les faibles effectifs. "
              "Si une demande ne peut être calculée, indique-le. "
              "Un tableau croisé et un graphique sont déjà affichés pour les avis ; ne les recopie pas intégralement.\n"
              "Question : " + question + "\nDonnées : " + json.dumps(results, ensure_ascii=False, default=str))
    last = ""
    for model in models:
        for attempt in range(2):
            try:
                response = client.models.generate_content(model=model, contents=prompt)
                if response.text: return response.text, None
                last = "Réponse vide"
                break
            except Exception as exc:
                last = f"{type(exc).__name__} : {str(exc)[:160]}"
                code = str(exc)
                if any(x in code for x in ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED")) and attempt == 0:
                    time.sleep(1.5)
                    continue
                break
    return None, last

def render_assistant(frame, reviews_loader):
    st.markdown("### 🤖 Assistant IA — Marché Airbnb de Lyon")
    st.caption("Calculs effectués sur les annonces filtrées ; Gemini rédige une synthèse facultative. En cas d'indisponibilité, les résultats et graphiques locaux restent accessibles.")
    st.info("Exemples : « Compare les prix médians par quartier », « Quels types de logements ont les meilleures notes ? », « Combien d'avis par type et par année ? »")
    try:
        key = str(st.secrets.get("GEMINI_API_KEY", ""))
        model = str(st.secrets.get("GEMINI_MODEL", "gemini-3.8-flash"))
    except Exception: key, model = "", "gemini-3.8-flash"
    enabled = bool(key and not key.startswith(("COLLER_ICI", "REMPLACE_ICI")))
    if not enabled: st.warning("Clé Gemini absente : le mode statistiques locales reste utilisable. Configurez .streamlit/secrets.toml pour activer la rédaction IA.")
    sig = (len(frame), int(pd.util.hash_pandas_object(frame.index.to_series(), index=False).sum()))
    if st.session_state.get("ai_filter_signature") != sig:
        st.session_state.ai_filter_signature = sig
        st.session_state.ai_history = []
    for item in st.session_state.get("ai_history", []):
        with st.chat_message(item["role"]):
            st.markdown(item["content"])
            if item.get("results"): _visuals(item["results"])
    question = st.chat_input("Ex. Combien d'avis par type et par année ?", key="lyon_ai_chat")
    if not question: return
    st.session_state.ai_history.append({"role":"user", "content":question})
    with st.chat_message("user"): st.markdown(question)
    with st.chat_message("assistant"):
        with st.spinner("Calcul des statistiques locales…"):
            results = []
            for op, metric, group in _select(question):
                if op == "aggregate": results.append(_aggregate(frame, metric, group))
                elif op == "reviews": results.append(_review_counts(frame, reviews_loader))
                else: results.append({"erreur":"Cette information n'est pas disponible dans les datasets."})
        local = _local_text(results)
        st.markdown(local)
        _visuals(results)
        if enabled and any("erreur" not in r for r in results):
            with st.spinner("Gemini rédige une courte synthèse (repli local si indisponible)…"):
                try: summary, error = _call_gemini(key, model, question, results)
                except Exception as exc: summary, error = None, f"{type(exc).__name__}: {str(exc)[:130]}"
            if summary:
                st.markdown("**Synthèse IA**\n\n" + summary)
                local += "\n\n**Synthèse IA**\n\n" + summary
            else:
                st.caption("Gemini temporairement indisponible ; les statistiques ci-dessus restent valides. " + (error or ""))
    st.session_state.ai_history.append({"role":"assistant", "content":local, "results":results})

"""
evaluate_model.py
Script de evaluación experimental rigurosa para el Sistema Recomendador
Fase 5 de CRISP-DM: Evaluación Técnica y Traducción a Objetivos de Negocio.

Calcula:
1. Matriz de Confusión (TP, FP, FN, TN)
2. Métricas de Clasificación y Ranking: Precision@k, Recall@k, F1-Score@k, Specificity, Accuracy, Hit Rate@k
3. Cobertura de Catálogo y Cobertura de Usuarios
4. Comparativa de 4 Modelos:
   - Baseline 2025: Carrusel Aleatorio (Random)
   - Baseline Popularidad: Top-N Global
   - Recomendador Híbrido: Cascada Colaborativo + Contenido + Popularidad
   - Recomendador Híbrido + Re-ranking Prescriptivo por Margen/Precio (alpha=0.2)
5. Simulación Financiera del Objetivo de Negocio (+10% en Ganancias para 2026)
"""

import sys
import os
import random
import numpy as np
import pandas as pd
from collections import defaultdict
from sklearn.metrics.pairwise import cosine_similarity

# Asegurar path al módulo principal
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from database import get_db_connection
from schemas import INTERACTION_WEIGHTS, InteractionType

# Fijar semilla para reproducibilidad científica
SEED = 42
random.seed(SEED)
np.random.seed(SEED)

def fetch_catalog():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, genre, price, attributes, author FROM items ORDER BY id;")
            items = cur.fetchall()
            return [dict(it) for it in items]
    finally:
        conn.close()

def generate_evaluation_benchmark_dataset(catalog, num_users=60):
    """
    Genera un conjunto de datos de prueba coherente con arquetipos de usuarios
    siguiendo la consigna del comitente: cada usuario compra entre 7 y 10 libros,
    y realiza interacciones previas (VIEW, SEARCH, ADD_TO_CART, FAVORITE, PURCHASE).
    """
    clusters = {
        "SciFi_Distopia": ["Ciencia Ficción", "Distopía", "Post-apocalíptico"],
        "Novela_RealismoMagico": ["Novela", "Realismo Mágico", "Cuento"],
        "Terror_Misterio_Thriller": ["Terror", "Misterio", "Thriller", "Crimen"],
        "Fantasia_Aventura": ["Fantasía", "Aventura", "Juvenil"],
        "Clasico_Ensayo": ["Clásico", "Ensayo", "Divulgación", "Memorias"]
    }

    # Mapear libros por género
    genre_to_items = defaultdict(list)
    for it in catalog:
        genre_to_items[it["genre"]].append(it)

    users = []
    interactions = []
    pref_id = 1

    for u_id in range(1, num_users + 1):
        cluster_name = random.choice(list(clusters.keys()))
        target_genres = clusters[cluster_name]
        
        # Libros candidatos afines al cluster
        affinity_pool = []
        for g in target_genres:
            affinity_pool.extend(genre_to_items.get(g, []))
        
        # Libros de exploración (otros géneros)
        other_pool = [it for it in catalog if it not in affinity_pool]

        # Consigna: 7 a 10 compras por usuario
        num_purchases = random.randint(7, 10)
        
        # 85% de los libros del cluster afín, 15% de exploración
        k_affinity = min(len(affinity_pool), int(num_purchases * 0.85))
        k_other = num_purchases - k_affinity
        
        purchased_items = random.sample(affinity_pool, k_affinity)
        if other_pool and k_other > 0:
            purchased_items.extend(random.sample(other_pool, min(k_other, len(other_pool))))

        # Generar interacciones completas para cada libro comprado (embudo de conversión)
        user_interactions = []
        for it in purchased_items:
            # Todo libro comprado pasó por VIEW y ADD_TO_CART o FAVORITE
            user_interactions.append({"user_id": u_id, "item_id": it["id"], "interaction_type": "VIEW", "value": 1})
            if random.random() < 0.6:
                user_interactions.append({"user_id": u_id, "item_id": it["id"], "interaction_type": "SEARCH", "value": 2})
            if random.random() < 0.7:
                user_interactions.append({"user_id": u_id, "item_id": it["id"], "interaction_type": "ADD_TO_CART", "value": 5})
            if random.random() < 0.4:
                user_interactions.append({"user_id": u_id, "item_id": it["id"], "interaction_type": "FAVORITE", "value": 7})
            user_interactions.append({"user_id": u_id, "item_id": it["id"], "interaction_type": "PURCHASE", "value": 10})

        # Libros adicionales que el usuario solo vio o buscó pero NO compró (ruido / señal débil)
        browse_sample = random.sample(catalog, random.randint(3, 6))
        for it in browse_sample:
            if it not in purchased_items:
                user_interactions.append({"user_id": u_id, "item_id": it["id"], "interaction_type": "VIEW", "value": 1})
                if random.random() < 0.3:
                    user_interactions.append({"user_id": u_id, "item_id": it["id"], "interaction_type": "SEARCH", "value": 2})

        users.append({
            "id": u_id,
            "username": f"user_bench_{u_id}",
            "cluster": cluster_name,
            "preferred_genres": target_genres[:2]
        })
        interactions.extend(user_interactions)

    return users, interactions

class SimulatedOfflineRecommender:
    """
    Implementación offline idéntica a la lógica de RecommenderEngine
    para evaluar reproduciblemente sobre partición Train/Test.
    """
    def __init__(self, catalog, train_interactions, users):
        self.catalog = {it["id"]: it for it in catalog}
        self.all_item_ids = list(self.catalog.keys())
        self.users = {u["id"]: u for u in users}
        self.train_df = pd.DataFrame(train_interactions)
        
        # 1. Matriz de preferencias Train
        if not self.train_df.empty:
            self.matrix = self.train_df.pivot_table(
                index="user_id", columns="item_id", values="value", aggfunc="max"
            ).fillna(0)
            
            # Similitud Coseno
            self.sim_matrix = cosine_similarity(self.matrix)
            self.sim_df = pd.DataFrame(self.sim_matrix, index=self.matrix.index, columns=self.matrix.index)
        else:
            self.matrix = pd.DataFrame()
            self.sim_df = pd.DataFrame()

        # 2. Popularidad global Train
        if not self.train_df.empty:
            self.popularity = self.train_df.groupby("item_id")["value"].count().sort_values(ascending=False)
        else:
            self.popularity = pd.Series(dtype=float)

    def recommend_random(self, user_id, n=10):
        # Línea base 2025: Carrusel aleatorio
        return random.sample(self.all_item_ids, n)

    def recommend_popularity(self, user_id, n=10, excluded_ids=None):
        excluded = set(excluded_ids or [])
        recs = [iid for iid in self.popularity.index if iid not in excluded][:n]
        if len(recs) < n:
            remaining = [iid for iid in self.all_item_ids if iid not in excluded and iid not in recs]
            recs.extend(remaining[:n - len(recs)])
        return recs[:n]

    def recommend_hybrid(self, user_id, n=10, apply_price_rerank=False, alpha=0.2):
        recs = []
        seen = set()

        # Libros ya comprados en Train se excluyen
        user_train = self.train_df[self.train_df["user_id"] == user_id]
        purchased_in_train = set(user_train[user_train["interaction_type"].isin(["PURCHASE", "FAVORITE"])]["item_id"])
        seen.update(purchased_in_train)

        candidate_scores = {}

        # 1. Filtro Colaborativo
        if user_id in self.sim_df.index:
            similar_users = self.sim_df[user_id].sort_values(ascending=False)[1:6]
            sim_dict = similar_users[similar_users > 0].to_dict()
            
            if sim_dict:
                sub_pref = self.train_df[self.train_df["user_id"].isin(sim_dict.keys())].copy()
                if not sub_pref.empty:
                    sub_pref["sim"] = sub_pref["user_id"].map(sim_dict)
                    sub_pref["weighted"] = sub_pref["value"] * sub_pref["sim"]
                    
                    scores = sub_pref.groupby("item_id")["weighted"].sum() / sub_pref.groupby("item_id")["sim"].sum()
                    scores = scores.sort_values(ascending=False)
                    
                    for iid, sc in scores.items():
                        if iid not in seen:
                            recs.append(iid)
                            seen.add(iid)
                            candidate_scores[iid] = float(sc)
                            if len(recs) >= n:
                                break

        # 2. Content-Based fallback si faltan
        if len(recs) < n:
            user_genres = self.users.get(user_id, {}).get("preferred_genres", [])
            if user_genres:
                cb_candidates = [
                    it["id"] for it in self.catalog.values()
                    if it["id"] not in seen and any(g.lower() in it["genre"].lower() for g in user_genres)
                ]
                # Ordenar por popularidad
                cb_candidates.sort(key=lambda x: self.popularity.get(x, 0), reverse=True)
                for iid in cb_candidates:
                    recs.append(iid)
                    seen.add(iid)
                    candidate_scores[iid] = float(self.popularity.get(iid, 1)) + 1.0
                    if len(recs) >= n:
                        break

        # 3. Fallback a Popularidad
        if len(recs) < n:
            pop_candidates = [iid for iid in self.popularity.index if iid not in seen]
            for iid in pop_candidates:
                recs.append(iid)
                seen.add(iid)
                candidate_scores[iid] = float(self.popularity.get(iid, 1)) + 0.5
                if len(recs) >= n:
                    break

        if len(recs) < n:
            remaining = [iid for iid in self.all_item_ids if iid not in seen]
            recs.extend(remaining[:n - len(recs)])
            for iid in recs:
                if iid not in candidate_scores:
                    candidate_scores[iid] = 1.0

        recs = recs[:n]

        # 4. Re-ranking por precio opcional
        if apply_price_rerank:
            items_obj = [self.catalog[iid] for iid in recs]
            prices = [float(it.get("price", 0.0) or 0.0) for it in items_obj]
            min_p = min(prices) if prices else 0.0
            max_p = max(prices) if prices else 0.0

            reranked_scores = {}
            for idx, iid in enumerate(recs):
                raw_score = candidate_scores.get(iid, 1.0)
                price = prices[idx]
                norm_price = (price - min_p) / (max_p - min_p) if max_p > min_p else 0.5
                reranked_scores[iid] = raw_score * (1.0 + alpha * norm_price)
            
            recs.sort(key=lambda x: reranked_scores[x], reverse=True)

        return recs

def run_rigorous_evaluation():
    print("="*70)
    print("FASE 5 CRISP-DM: EVALUACIÓN EXPERIMENTAL RIGUROSA")
    print("="*70)

    catalog = fetch_catalog()
    print(f"Catálogo cargado: {len(catalog)} libros (Precios: ${min(it['price'] for it in catalog)} - ${max(it['price'] for it in catalog)})")

    # 1. Generar Benchmark de prueba con 60 usuarios
    users, all_interactions = generate_evaluation_benchmark_dataset(catalog, num_users=60)
    print(f"Dataset sintético generado: {len(users)} usuarios, {len(all_interactions)} interacciones.")

    # 2. Partición Train (75%) / Test (25%)
    # Para cada usuario, se reservan 2 o 3 compras para el Test Set (Ground Truth relevante)
    train_interactions = []
    test_ground_truth = defaultdict(set) # user_id -> set of relevant test items

    for u in users:
        u_id = u["id"]
        u_ints = [it for it in all_interactions if it["user_id"] == u_id]
        # Interacciones de alta relevancia (PURCHASE o FAVORITE)
        high_val_items = list({it["item_id"] for it in u_ints if it["interaction_type"] in ["PURCHASE", "FAVORITE"]})
        
        # Test split: 25% de los ítems comprados
        k_test = max(2, int(len(high_val_items) * 0.25))
        test_items = set(random.sample(high_val_items, k_test))
        test_ground_truth[u_id] = test_items
        
        # Train split: todas las interacciones excepto las compras de test
        for it in u_ints:
            if not (it["item_id"] in test_items and it["interaction_type"] in ["PURCHASE", "FAVORITE"]):
                train_interactions.append(it)

    print(f"Train Set: {len(train_interactions)} interacciones.")
    print(f"Test Set: {sum(len(v) for v in test_ground_truth.values())} compras/favoritos retenidos como Ground Truth.")

    # 3. Instanciar recomendador offline
    engine = SimulatedOfflineRecommender(catalog, train_interactions, users)

    # 4. Evaluar los 4 modelos para N=5 y N=10
    models = {
        "Baseline 2025: Carrusel Aleatorio": lambda u, n: engine.recommend_random(u, n),
        "Baseline: Top-N Popularidad": lambda u, n: engine.recommend_popularity(u, n),
        "Recomendador Híbrido (Cascada CF+CB+Pop)": lambda u, n: engine.recommend_hybrid(u, n, apply_price_rerank=False),
        "Recomendador Híbrido + Re-ranking Prescriptivo": lambda u, n: engine.recommend_hybrid(u, n, apply_price_rerank=True, alpha=0.2)
    }

    results = []

    for model_name, model_fn in models.items():
        for N in [5, 10]:
            total_TP = 0
            total_FP = 0
            total_FN = 0
            total_TN = 0
            
            precisions = []
            recalls = []
            f1s = []
            hit_rates = []
            recommended_catalog_items = set()
            revenue_per_user = []

            for u in users:
                u_id = u["id"]
                truth = test_ground_truth[u_id]
                rec_ids = model_fn(u_id, N)
                rec_set = set(rec_ids)
                recommended_catalog_items.update(rec_ids)

                # Matriz de Confusión sobre el catálogo de 100 libros
                # Positivo = El modelo lo recomienda
                # Relevante = Está en el Ground Truth de test
                TP = len(rec_set & truth)
                FP = len(rec_set - truth)
                FN = len(truth - rec_set)
                TN = 100 - (TP + FP + FN)

                total_TP += TP
                total_FP += FP
                total_FN += FN
                total_TN += TN

                prec = TP / N if N > 0 else 0.0
                rec = TP / len(truth) if len(truth) > 0 else 0.0
                f1 = (2 * prec * rec) / (prec + rec) if (prec + rec) > 0 else 0.0
                hit = 1.0 if TP > 0 else 0.0

                precisions.append(prec)
                recalls.append(rec)
                f1s.append(f1)
                hit_rates.append(hit)

                # Simulación de ingresos por usuario:
                # Cada acierto (TP) genera una compra del precio real del libro recomendado.
                # Además, una pequeña tasa basal de compra orgánica en FP (2% de compra casual).
                u_revenue = sum(float(catalog[iid - 1]["price"]) for iid in (rec_set & truth))
                for fp_id in (rec_set - truth):
                    if random.random() < 0.03: # 3% conversión casual
                        u_revenue += float(catalog[fp_id - 1]["price"])
                revenue_per_user.append(u_revenue)

            # Métricas agregadas
            mean_prec = np.mean(precisions)
            mean_rec = np.mean(recalls)
            mean_f1 = np.mean(f1s)
            mean_hit = np.mean(hit_rates)
            catalog_cov = len(recommended_catalog_items) / len(catalog) * 100.0
            specificity = total_TN / (total_TN + total_FP)
            accuracy = (total_TP + total_TN) / (total_TP + total_TN + total_FP + total_FN)
            avg_revenue = np.mean(revenue_per_user)

            results.append({
                "Modelo": model_name,
                "Top-N": N,
                "TP": total_TP,
                "FP": total_FP,
                "FN": total_FN,
                "TN": total_TN,
                "Precision@k": round(mean_prec, 4),
                "Recall@k": round(mean_rec, 4),
                "F1-Score@k": round(mean_f1, 4),
                "Specificity": round(specificity, 4),
                "Accuracy": round(accuracy, 4),
                "Hit Rate@k": round(mean_hit * 100, 2),
                "Catalog Cov %": round(catalog_cov, 1),
                "Avg Revenue/User ($)": round(avg_revenue, 2)
            })

    df_res = pd.DataFrame(results)

    # Calcular % de incremento en ganancias respecto a Baseline 2025 para N=10
    baseline_rev = df_res[(df_res["Modelo"] == "Baseline 2025: Carrusel Aleatorio") & (df_res["Top-N"] == 10)]["Avg Revenue/User ($)"].values[0]
    df_res["Incremento Ganancias vs 2025 (%)"] = df_res["Avg Revenue/User ($)"].apply(
        lambda r: round(((r - baseline_rev) / baseline_rev) * 100.0, 2)
    )

    print("\nTABLA DE RESULTADOS DE EVALUACIÓN (Métricas Técnicas y de Negocio):")
    print(df_res.to_string(index=False))

    # Guardar en archivo CSV para el informe
    out_csv = "evaluation_results.csv"
    df_res.to_csv(out_csv, index=False)
    print(f"\nResultados exportados a {out_csv} exitosamente.")

    # Resumen de Matriz de Confusión para N=10
    print("\n" + "="*70)
    print("MATRICES DE CONFUSIÓN AGREGADAS (Top-10):")
    for row in df_res[df_res["Top-N"] == 10].itertuples():
        print(f"\n>>> {row.Modelo}:")
        print(f"    [ TP: {row.TP:>4} | FP: {row.FP:>4} ]")
        print(f"    [ FN: {row.FN:>4} | TN: {row.TN:>4} ]")
        print(f"    Precision@10: {row._7*100:.2f}% | Recall@10: {row._8*100:.2f}% | F1: {row._9:.4f}")
        print(f"    Ingreso Simulado por Usuario: ${row._13:,.2f} (Delta vs 2025: {row._14:+.2f}%)")

    return df_res

if __name__ == "__main__":
    run_rigorous_evaluation()

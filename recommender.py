import logging
import pandas as pd
import numpy as np
import psycopg2.extras
from sklearn.metrics.pairwise import cosine_similarity
from database import get_db_connection
from helpers.helpers import map_item_to_schema, add_unique_items, get_user_preferred_genres

logger = logging.getLogger(__name__)

class RecommenderEngine:
    def __init__(self):
        pass

    def get_recommendations(self, user_id: int, n: int):
        dbConnection = get_db_connection()
        final_recs = []
        
        try:
            # Obtener únicamente los ítems que el usuario YA compró o guardó en favoritos para exclusión
            excluded_ids = self._get_excluded_items_for_user(dbConnection, user_id)
            seen_ids = set(excluded_ids) # Evitar recomendar lo ya comprado/favorito o duplicados

            # 1. Estrategia Colaborativa (usando tabla user_similarities)
            has_history = False
            with dbConnection.cursor() as cur:
                cur.execute("SELECT 1 FROM preferences WHERE user_id = %s LIMIT 1", (user_id,))
                has_history = cur.fetchone() is not None

            if has_history:
                logger.info(f"User {user_id}: Ejecutando Colaborativo...")
                collab_items = self._collaborative_strategy(dbConnection, user_id, n, excluded_ids=excluded_ids)
                add_unique_items(final_recs, seen_ids, collab_items, n)

            # 2. Estrategia Content-Based (si faltan ítems)
            if len(final_recs) < n:
                needed = n - len(final_recs)
                genres = get_user_preferred_genres(dbConnection, user_id)
                
                if genres:
                    logger.info(f"User {user_id}: Ejecutando Content-Based (Géneros: {genres})...")
                    content_items = self._fetch_items_by_genres(dbConnection, genres, needed, exclude_ids=seen_ids)
                    add_unique_items(final_recs, seen_ids, content_items, n)

            # 3. Estrategia de Popularidad (si faltan ítems)
            if len(final_recs) < n:
                needed = n - len(final_recs)
                logger.info(f"User {user_id}: Ejecutando Popularidad...")
                pop_items = self._fetch_popular_items(dbConnection, needed, exclude_ids=seen_ids)
                add_unique_items(final_recs, seen_ids, pop_items, n)

            # 4. Analítica Prescriptiva: Re-ranking por precio para optimizar margen comercial
            final_recs = self._apply_price_reranking(final_recs, alpha=0.2)

            logger.info(f"Recomendación final: {len(final_recs)} items generados.")
            return [map_item_to_schema(r) for r in final_recs]

        except Exception as e:
            logger.error(f"Error en get_recommendations: {e}")
            return []
        finally:
            dbConnection.close()

    def _get_excluded_items_for_user(self, dbConnection, user_id: int) -> set:
        """
        Retorna únicamente los IDs de los libros que el usuario YA COMPRÓ (PURCHASE)
        o agregó a FAVORITOS (FAVORITE). Las VISTAS (VIEW) o BÚSQUEDAS (SEARCH) NO se excluyen.
        """
        try:
            with dbConnection.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT item_id 
                    FROM preferences 
                    WHERE user_id = %s AND (interaction_type IN ('PURCHASE', 'FAVORITE') OR value >= 7)
                    """,
                    (user_id,)
                )
                rows = cur.fetchall()
                return {row['item_id'] for row in rows}
        except Exception as e:
            logger.error(f"Error en _get_excluded_items_for_user: {e}")
            return set()

    def compute_and_store_similarities(self, dbConnection):
        """
        Calcula en batch la matriz de similitud de cosenos entre usuarios
        y la persiste en la tabla PostgreSQL `user_similarities`.
        """
        try:
            with dbConnection.cursor() as cur:
                cur.execute("SELECT user_id, item_id, value FROM preferences")
                data = cur.fetchall()
            
            if not data:
                return

            df_all = pd.DataFrame(data)
            df_all['value'] = pd.to_numeric(df_all['value'], errors='coerce').fillna(0)
            matrix = df_all.pivot_table(index='user_id', columns='item_id', values='value').fillna(0)

            if matrix.empty:
                return

            sim_matrix = cosine_similarity(matrix)
            sim_df = pd.DataFrame(sim_matrix, index=matrix.index, columns=matrix.index)

            records = []
            for u1 in sim_df.index:
                for u2 in sim_df.columns:
                    if u1 != u2:
                        score = float(sim_df.loc[u1, u2])
                        if score > 0:
                            records.append((int(u1), int(u2), score))

            if records:
                with dbConnection.cursor() as cur:
                    psycopg2.extras.execute_values(
                        cur,
                        """
                        INSERT INTO user_similarities (user_id_1, user_id_2, similarity_score)
                        VALUES %s
                        ON CONFLICT (user_id_1, user_id_2)
                        DO UPDATE SET similarity_score = EXCLUDED.similarity_score, updated_at = CURRENT_TIMESTAMP
                        """,
                        records
                    )
                    dbConnection.commit()
                logger.info(f"Persistidas {len(records)} similitudes de usuario en user_similarities.")
        except Exception as e:
            dbConnection.rollback()
            logger.error(f"Error guardando similitudes en BD: {e}")

    def _collaborative_strategy(self, dbConnection, user_id: int, n: int, excluded_ids: set = None):
        if excluded_ids is None:
            excluded_ids = set()

        try:
            # Consultar similitudes precalculadas desde user_similarities
            with dbConnection.cursor() as cur:
                cur.execute(
                    """
                    SELECT user_id_2, similarity_score 
                    FROM user_similarities 
                    WHERE user_id_1 = %s AND similarity_score > 0
                    ORDER BY similarity_score DESC 
                    LIMIT 5
                    """,
                    (user_id,)
                )
                sim_rows = cur.fetchall()

            # Fallback de primera ejecución: si no hay similitudes persistidas para este usuario, computar en el momento
            if not sim_rows:
                self.compute_and_store_similarities(dbConnection)
                with dbConnection.cursor() as cur:
                    cur.execute(
                        """
                        SELECT user_id_2, similarity_score 
                        FROM user_similarities 
                        WHERE user_id_1 = %s AND similarity_score > 0
                        ORDER BY similarity_score DESC 
                        LIMIT 5
                        """,
                        (user_id,)
                    )
                    sim_rows = cur.fetchall()

            if not sim_rows:
                return []

            similar_users = [row['user_id_2'] for row in sim_rows]
            sim_dict = {row['user_id_2']: row['similarity_score'] for row in sim_rows}

            # Obtener interacciones de los usuarios similares
            with dbConnection.cursor() as cur:
                cur.execute(
                    "SELECT user_id, item_id, value FROM preferences WHERE user_id = ANY(%s)",
                    (similar_users,)
                )
                pref_rows = cur.fetchall()

            if not pref_rows:
                return []

            df_pref = pd.DataFrame(pref_rows)
            df_pref['value'] = pd.to_numeric(df_pref['value'], errors='coerce').fillna(0)
            df_pref['sim'] = df_pref['user_id'].map(sim_dict)
            df_pref['weighted_val'] = df_pref['value'] * df_pref['sim']

            # Calcular score ponderado por ítem
            item_scores = df_pref.groupby('item_id')['weighted_val'].sum() / df_pref.groupby('item_id')['sim'].sum()
            item_scores = item_scores.sort_values(ascending=False)

            # Filtrar ítems excluidos (PURCHASE/FAVORITE del usuario)
            candidate_ids = [int(iid) for iid in item_scores.index if int(iid) not in excluded_ids][:n * 2]

            if not candidate_ids:
                return []

            query_items = "SELECT id, name, genre, attributes, author, price FROM items WHERE id = ANY(%s)"
            with dbConnection.cursor() as cur:
                cur.execute(query_items, (candidate_ids,))
                items_data = cur.fetchall()

            if not items_data:
                return []

            df_items = pd.DataFrame(items_data)
            df_items['sort_order'] = df_items['id'].apply(
                lambda x: candidate_ids.index(x) if x in candidate_ids else 999
            )
            df_items = df_items.sort_values('sort_order').head(n)

            results = df_items.to_dict(orient='records')
            for item in results:
                item['_source'] = 'collaborative'
                iid = int(item['id'])
                item['_score'] = float(item_scores.get(iid, 1.0))

            return results

        except Exception as e:
            logger.error(f"Error en Algoritmo Colaborativo: {e}")
            return []

    def _fetch_items_by_genres(self, dbConnection, genres, limit, exclude_ids=None):
        patterns = [f"%{g}%" for g in genres]

        query = """
            SELECT i.id, i.name, i.genre, i.attributes, i.author, i.price, COUNT(p.id) as pref_count
            FROM items i
            LEFT JOIN preferences p ON i.id = p.item_id
            WHERE i.genre ILIKE ANY(%s)
        """
        params = [patterns]

        if exclude_ids and len(exclude_ids) > 0:
            query += " AND NOT (i.id = ANY(%s))"
            params.append(list(exclude_ids))
        
        query += " GROUP BY i.id ORDER BY COUNT(p.id) DESC LIMIT %s"
        params.append(limit)

        try:
            with dbConnection.cursor() as cur:
                cur.execute(query, params)
                results = cur.fetchall()
                for item in results: 
                    item['_source'] = 'content-based'
                    item['_score'] = float(item.get('pref_count', 1.0)) + 1.0
                return results
        except Exception as e:
            logger.error(f"Error SQL Content-Based: {e}")
            return []

    def _fetch_popular_items(self, dbConnection, limit, exclude_ids=None):
        query = """
            SELECT i.id, i.name, i.genre, i.attributes, i.author, i.price, COUNT(p.id) as pref_count
            FROM items i
            LEFT JOIN preferences p ON i.id = p.item_id
        """
        params = []

        if exclude_ids and len(exclude_ids) > 0:
            query += " WHERE NOT (i.id = ANY(%s))"
            params.append(list(exclude_ids))
        
        query += " GROUP BY i.id ORDER BY COUNT(p.id) DESC LIMIT %s"
        params.append(limit)

        try:
            with dbConnection.cursor() as cur:
                cur.execute(query, params)
                results = cur.fetchall()
                for item in results: 
                    item['_source'] = 'popular'
                    item['_score'] = float(item.get('pref_count', 1.0)) + 0.5
                return results
        except Exception as e:
            logger.error(f"Error SQL Popularity: {e}")
            return []

    def _apply_price_reranking(self, items: list, alpha: float = 0.2) -> list:
        """
        Re-ranking prescriptivo basado en el precio del ítem para maximizar el margen comercial:
        Final_Score(u, i) = Recommendation_Score(u, i) * (1 + alpha * normalized_price(i))
        """
        if not items:
            return items

        prices = []
        for item in items:
            attrs = item.get('attributes') or {}
            price_val = item.get('price')
            if price_val is None and isinstance(attrs, dict):
                price_val = attrs.get('price')
            try:
                prices.append(float(price_val) if price_val is not None else 0.0)
            except (ValueError, TypeError):
                prices.append(0.0)

        min_p = min(prices) if prices else 0.0
        max_p = max(prices) if prices else 0.0

        for idx, item in enumerate(items):
            raw_score = float(item.get('_score', 1.0))
            price = prices[idx]

            if max_p > min_p:
                norm_price = (price - min_p) / (max_p - min_p)
            else:
                norm_price = 0.5 if max_p > 0 else 0.0

            final_score = raw_score * (1.0 + alpha * norm_price)
            item['_score'] = final_score

        # Re-ordenar items por score prescriptivo final
        items.sort(key=lambda x: float(x.get('_score', 0.0)), reverse=True)
        return items
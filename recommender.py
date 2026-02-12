import logging
import pandas as pd
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from database import get_db_connection
from helpers.helpers import map_item_to_schema, add_unique_items, get_user_preferred_genres

logger = logging.getLogger(__name__)

class RecommenderEngine:
    def __init__(self):
        pass

    # ESTRATEGIA DE LLENADO EN CASCADA

    def get_recommendations(self, user_id: int, n: int):
        dbConnection = get_db_connection()
        final_recs = []
        seen_ids = set() # Para evitar duplicados
        
        try:
            # Intentamos primero con el colaborativo SOLO si el usuario tiene historial de preferencias
            has_history = False
            with dbConnection.cursor() as cur:
                cur.execute("SELECT 1 FROM preferences WHERE user_id = %s LIMIT 1", (user_id,))
                has_history = cur.fetchone() is not None

            if has_history:
                logger.info(f"User {user_id}: Ejecutando Colaborativo...")
                collab_items = self._collaborative_strategy(dbConnection, user_id, n)
                add_unique_items(final_recs, seen_ids, collab_items, n)

            # Si el colaborativo no llenó todas las recomendaciones, intentamos con el content-based.
            if len(final_recs) < n:
                needed = n - len(final_recs)
                genres = get_user_preferred_genres(dbConnection, user_id)
                
                if genres:
                    logger.info(f"User {user_id}: Ejecutando Content-Based (Géneros: {genres})...")
                    # Pasamos seen_ids para excluir lo que ya recomendó el colaborativo
                    content_items = self._fetch_items_by_genres(dbConnection, genres, needed, exclude_ids=seen_ids)
                    add_unique_items(final_recs, seen_ids, content_items, n)

            # Rellenar con Popularidad si todavia faltan recomendaciones.
            if len(final_recs) < n:
                needed = n - len(final_recs)
                logger.info(f"User {user_id}: Ejecutando Popularidad")
                pop_items = self._fetch_popular_items(dbConnection, needed, exclude_ids=seen_ids)
                add_unique_items(final_recs, seen_ids, pop_items, n)

            logger.info(f"Recomendación final: {len(final_recs)} items generados.")
            
            return [map_item_to_schema(r) for r in final_recs]

        except Exception as e:
            logger.error(f"Error en get_recommendations: {e}")
            return []
        finally:
            dbConnection.close()


    # Busca items que coincidan con los generos preferidos.
    def _fetch_items_by_genres(self, dbConnection, genres, limit, exclude_ids=None):
        patterns = [f"%{g}%" for g in genres]

        query = """
            SELECT i.id, i.name, i.genre, i.attributes, i.author, i.price
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
                for item in results: item['_source'] = 'content-based'
                return results
        except Exception as e:
            logger.error(f"Error SQL Content-Based: {e}")
            return []

    def _fetch_popular_items(self, dbConnection, limit, exclude_ids=None):
        query = """
            SELECT i.id, i.name, i.genre, i.attributes, i.author, i.price
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
                for item in results: item['_source'] = 'popular'
                return results
        except Exception as e:
            logger.error(f"Error SQL Popularity: {e}")
            return []

    def _collaborative_strategy(self, dbConnection, user_id, n):
        try:

            with dbConnection.cursor() as cur:
                cur.execute("SELECT user_id, item_id, value FROM preferences")
                data = cur.fetchall()
            df_all = pd.DataFrame(data)
            
            if df_all.empty: return []

            # Asegurar tipos numéricos para evitar errores.
            df_all['value'] = pd.to_numeric(df_all['value'], errors='coerce').fillna(0)
            
            # 2. Pivot Table
            matrix = df_all.pivot_table(index='user_id', columns='item_id', values='value').fillna(0)

            if user_id not in matrix.index: return []

            # 3. Similitud Coseno
            sim_matrix = cosine_similarity(matrix)
            sim_df = pd.DataFrame(sim_matrix, index=matrix.index, columns=matrix.index)
            
            # 4. Encontrar usuarios similares (Top 5)
            similar_users = sim_df[user_id].sort_values(ascending=False)[1:6].index
            if len(similar_users) == 0: return []

            # 5. Predicción (Promedio de lo que compraron los similares)
            recs_scores = matrix.loc[similar_users].mean().sort_values(ascending=False)
            
            # 6. Filtrar lo que el usuario YA compró
            user_bought = matrix.loc[user_id]
            # Traemos un poco más de 'n' (n*2) para tener margen
            candidate_ids = recs_scores[user_bought == 0].head(n * 2).index.tolist()
            
            if not candidate_ids: return []

            # 7. Obtener detalles de la BD
            
            if len(candidate_ids) == 1:
                query_items = "SELECT * FROM items WHERE id = %s"
                params = (candidate_ids[0],)
            else:
                # si hay mas de una id candidata hay que pasarsela con un IN y como una tupla.
                query_items = "SELECT * FROM items WHERE id IN %s"
                params = (tuple(candidate_ids),)

            with dbConnection.cursor() as cur:
                cur.execute(query_items, params)
                items_data = cur.fetchall()
            
            df_items = pd.DataFrame(items_data)
            
            # Reordenar segun el puntaje de recomendacion.
            df_items['sort_order'] = df_items['id'].apply(
                lambda x: candidate_ids.index(x) if x in candidate_ids else 999
            )
            df_items = df_items.sort_values('sort_order').head(n)
            
            results = df_items.to_dict(orient='records')
            for item in results: 
                item['_source'] = 'collaborative'
                iid = item['id']
                if iid in recs_scores:
                    item['_score'] = recs_scores[iid]
                else:
                    item['_score'] = 0.0
            
            return results
            
        except Exception as e:
            logger.error(f"Error en Algoritmo Colaborativo: {e}")
            return []
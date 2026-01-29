import logging
import pandas as pd
import json
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from database import get_db_connection

# Configuración de logs para ver qué pasa realmente
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class RecommenderEngine:
    def __init__(self):
        pass

    # ==========================================
    # 1. HELPERS (Utilería y Limpieza)
    # ==========================================
    
    def _parse_json_safe(self, data):
        """Intenta parsear JSON de forma segura."""
        if isinstance(data, dict): return data
        if isinstance(data, str):
            try: return json.loads(data)
            except: 
                try: return json.loads(data.replace("'", '"'))
                except: return {}
        return {}

    def _map_item_to_schema(self, row):
        """Mapeo final para que la API reciba los datos listos."""
        attrs = self._parse_json_safe(row.get('attributes'))
        
        # Inyección híbrida: Si author/price están afuera, los metemos en attributes
        if 'author' in row and row['author']: 
            attrs['author'] = row['author']
        if 'price' in row and row['price']: 
            try: attrs['price'] = float(row['price'])
            except: pass
        
        return {
            "id": int(row['id']),
            "name": str(row['name']),
            "genre": row.get('genre'),
            "attributes": attrs,
            "recommendation_source": row.get('_source', 'unknown'),
            "score": float(row.get('_score', 0.0))
        }

    def _get_user_preferred_genres(self, dbConnection, user_id):
        """Obtiene géneros preferidos del usuario de forma robusta."""
        try:
            with dbConnection.cursor() as cur:
                cur.execute("SELECT preferred_genres FROM users WHERE id = %s", (user_id,))
                row = cur.fetchone()
                if row and row['preferred_genres']:
                    data = row['preferred_genres']
                    # Manejar si Postgres devuelve lista o string JSON
                    return data if isinstance(data, list) else json.loads(data) if isinstance(data, str) else []
        except Exception as e:
            logger.warning(f"Error leyendo géneros usuario {user_id}: {e}")
            return []
        return []

    # ==========================================
    # 2. CORE: ESTRATEGIA DE LLENADO EN CASCADA (Waterfall)
    # ==========================================

    def get_recommendations(self, user_id: int, n: int):
        dbConnection = get_db_connection()
        final_recs = []
        seen_ids = set() # Para evitar duplicados
        
        try:
            # --- PASO 1: Intentar Colaborativo (Si hay historial) ---
            has_history = False
            with dbConnection.cursor() as cur:
                cur.execute("SELECT 1 FROM preferences WHERE user_id = %s LIMIT 1", (user_id,))
                has_history = cur.fetchone() is not None

            if has_history:
                logger.info(f"User {user_id}: Ejecutando Colaborativo...")
                collab_items = self._collaborative_strategy(dbConnection, user_id, n)
                self._add_unique_items(final_recs, seen_ids, collab_items, n)

            # --- PASO 2: Rellenar con Content-Based (Si faltan items) ---
            if len(final_recs) < n:
                needed = n - len(final_recs)
                genres = self._get_user_preferred_genres(dbConnection, user_id)
                
                if genres:
                    logger.info(f"User {user_id}: Ejecutando Content-Based (Géneros: {genres})...")
                    # Pasamos seen_ids para excluir lo que ya recomendó el colaborativo
                    content_items = self._fetch_items_by_genres(dbConnection, genres, needed, exclude_ids=seen_ids)
                    self._add_unique_items(final_recs, seen_ids, content_items, n)

            # --- PASO 3: Rellenar con Popularidad (Respaldo final) ---
            if len(final_recs) < n:
                needed = n - len(final_recs)
                logger.info(f"User {user_id}: Ejecutando Popularidad (Fallback)...")
                pop_items = self._fetch_popular_items(dbConnection, needed, exclude_ids=seen_ids)
                self._add_unique_items(final_recs, seen_ids, pop_items, n)

            logger.info(f"Recomendación final: {len(final_recs)} items generados.")
            
            # Mapeo final para cumplir contrato de API
            return [self._map_item_to_schema(r) for r in final_recs]

        except Exception as e:
            logger.error(f"Error CRÍTICO en get_recommendations: {e}")
            return []
        finally:
            dbConnection.close()

    def _add_unique_items(self, target_list, seen_set, new_items, limit):
        """Agrega items a la lista final respetando el límite y sin duplicados."""
        for item in new_items:
            if len(target_list) >= limit:
                break
            # Aseguramos que el ID sea int para el set
            try: iid = int(item['id'])
            except: continue
            
            if iid not in seen_set:
                target_list.append(item)
                seen_set.add(iid)

    # ==========================================
    # 3. MÉTODOS DE BÚSQUEDA (SQL CORREGIDO)
    # ==========================================

    def _fetch_items_by_genres(self, dbConnection, genres, limit, exclude_ids=None):
        # Preparar patrones para búsqueda flexible (ej: '%Terror%')
        patterns = [f"%{g}%" for g in genres]
        
        # Consulta base
        query = """
            SELECT i.id, i.name, i.genre, i.attributes, i.author, i.price
            FROM items i
            LEFT JOIN preferences p ON i.id = p.item_id
            WHERE i.genre ILIKE ANY(%s)
        """
        params = [patterns]

        # --- CORRECCIÓN CRÍTICA DE SQL ---
        # Solo agregamos la cláusula AND NOT si la lista NO está vacía
        if exclude_ids and len(exclude_ids) > 0:
            query += " AND NOT (i.id = ANY(%s))"
            params.append(list(exclude_ids)) # Postgres requiere lista para ANY
        
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

        # --- CORRECCIÓN CRÍTICA DE SQL ---
        # Solo agregamos WHERE NOT si la lista NO está vacía
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

    # ==========================================
    # 4. ESTRATEGIA COLABORATIVA
    # ==========================================

    def _collaborative_strategy(self, dbConnection, user_id, n):
        try:
            # 1. Cargar preferencias
            with dbConnection.cursor() as cur:
                cur.execute("SELECT user_id, item_id, value FROM preferences")
                data = cur.fetchall()
            df_all = pd.DataFrame(data)
            
            if df_all.empty: return []

            # Asegurar tipos numéricos para evitar errores de 'agg function failed'
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
            # Importante: Convertir IDs a tupla para SQL IN
            if len(candidate_ids) == 1:
                query_items = "SELECT * FROM items WHERE id = %s"
                params = (candidate_ids[0],)
            else:
                query_items = "SELECT * FROM items WHERE id IN %s"
                params = (tuple(candidate_ids),)

            with dbConnection.cursor() as cur:
                cur.execute(query_items, params)
                items_data = cur.fetchall()
            
            df_items = pd.DataFrame(items_data)
            
            # Reordenar según el puntaje de recomendación (SQL pierde el orden del IN)
            df_items['sort_order'] = df_items['id'].apply(
                lambda x: candidate_ids.index(x) if x in candidate_ids else 999
            )
            df_items = df_items.sort_values('sort_order').head(n)
            
            # Convert NaN attributes to {} if necessary, but RealDictCursor handles JSONs as dicts usually.
            # However, DataFrame might have NaNs for missing columns? No, fetchall results are consistent.
            
            # Convert NaN attributes to {} if necessary, but RealDictCursor handles JSONs as dicts usually.
            # However, DataFrame might have NaNs for missing columns? No, fetchall results are consistent.
            
            # Convert NaN attributes to {} if necessary, but RealDictCursor handles JSONs as dicts usually.
            # However, DataFrame might have NaNs for missing columns? No, fetchall results are consistent.
            
            results = df_items.to_dict(orient='records')
            for item in results: 
                item['_source'] = 'collaborative'
                # Inyectar el score (predicted rating)
                # item['id'] es int, recs_scores index son ints
                iid = item['id']
                if iid in recs_scores:
                    item['_score'] = recs_scores[iid]
                else:
                    item['_score'] = 0.0
            
            return results
            
        except Exception as e:
            logger.error(f"Error en Algoritmo Colaborativo: {e}")
            return []
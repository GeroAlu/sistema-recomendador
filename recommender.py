import pandas as pd
import json
from sklearn.metrics.pairwise import cosine_similarity
from database import get_db_connection

class RecommenderEngine:
    def __init__(self):
        pass

    # Función auxiliar para convertir texto JSON a Diccionario real
    def _parse_attributes(self, attr):
        if isinstance(attr, str):
            try:
                return json.loads(attr.replace("'", '"'))
            except:
                return {} 
        return attr if attr else {}

    def get_recommendations(self, user_id: int, n: int):
        conn = get_db_connection()
        try:
            # Verificar si el usuario tiene historial
            query_prefs = "SELECT item_id, value FROM preferences WHERE user_id = %s"
            df_user_prefs = pd.read_sql(query_prefs, conn, params=(user_id,))

            if df_user_prefs.empty:
                return self._cold_start_recommendations(conn, n)
            
            return self._collaborative_recommendations(conn, user_id, n)
        finally:
            conn.close()

    def _cold_start_recommendations(self, conn, n, user_id=None):
        preferred_genres = []
        if user_id:
            try:
                cur = conn.cursor()
                cur.execute("SELECT preferred_genres FROM users WHERE id = %s", (user_id,))
                row = cur.fetchone()
                if row and row['preferred_genres']:
                    data = row['preferred_genres']
                    # Asegurar que sea lista
                    preferred_genres = json.loads(data) if isinstance(data, str) else data
            except Exception as e:
                print(f"Error leyendo géneros: {e}")

        # --- PASO 2: Definir la consulta "Por Género" ---
        df = pd.DataFrame()
        
        # Solo intentamos filtrar si hay géneros definidos
        if preferred_genres and isinstance(preferred_genres, list) and len(preferred_genres) > 0:
            genres_tuple = tuple(preferred_genres)
            print(f"Buscando por géneros: {genres_tuple}") # Debug
            
            # Truco para tuplas de 1 elemento en SQL
            if len(genres_tuple) == 1:
                query_genre = """
                    SELECT i.id, i.name, i.attributes 
                    FROM items i
                    LEFT JOIN preferences p ON i.id = p.item_id
                    WHERE i.genre = %s
                    GROUP BY i.id, i.name, i.attributes
                    ORDER BY COUNT(p.id) DESC
                    LIMIT %s
                """
                params = (preferred_genres[0], n)
            else:
                query_genre = """
                    SELECT i.id, i.name, i.attributes 
                    FROM items i
                    LEFT JOIN preferences p ON i.id = p.item_id
                    WHERE i.genre IN %s
                    GROUP BY i.id, i.name, i.attributes
                    ORDER BY COUNT(p.id) DESC
                    LIMIT %s
                """
                params = (genres_tuple, n)
            
            try:
                df = pd.read_sql(query_genre, conn, params=params)
            except Exception as e:
                print(f"Error en consulta por género: {e}")

        # --- PASO 3: Fallback (Si el filtrado por género falló o vino vacío) ---
        if df.empty:
            print("Fallback: Buscando populares globales (sin filtro de género)")
            query_global = """
                SELECT i.id, i.name, i.attributes 
                FROM items i
                LEFT JOIN preferences p ON i.id = p.item_id 
                GROUP BY i.id, i.name, i.attributes
                ORDER BY COUNT(p.id) DESC
                LIMIT %s
            """
            df = pd.read_sql(query_global, conn, params=(n,))

        # --- PASO 4: Limpieza de datos (Evita errores de Pydantic) ---
        if not df.empty:
            # 1. Convertir atributos de texto a dict
            df['attributes'] = df['attributes'].apply(self._parse_attributes)
            # 2. Forzar ID a entero y eliminar basura
            df['id'] = pd.to_numeric(df['id'], errors='coerce').fillna(0).astype(int)
            df = df[df['id'] > 0]
            
            return df.to_dict(orient='records')
        
        return []

    def _collaborative_recommendations(self, conn, user_id, n):
        query = "SELECT user_id, item_id, value FROM preferences"
        df_all = pd.read_sql(query, conn)
        
        # Crear matriz User-Item
        matrix = df_all.pivot_table(index='user_id', columns='item_id', values='value').fillna(0)
        
        if user_id not in matrix.index:
            return self._cold_start_recommendations(conn, n)

        # Calcular similitud
        sim_matrix = cosine_similarity(matrix)
        sim_df = pd.DataFrame(sim_matrix, index=matrix.index, columns=matrix.index)
        
        # Encontrar usuarios similares
        similar_users = sim_df[user_id].sort_values(ascending=False)[1:6].index
        
        if len(similar_users) == 0:
             return self._cold_start_recommendations(conn, n)

        # Promediar gustos de similares
        recommendations = matrix.loc[similar_users].mean().sort_values(ascending=False)
        
        # Filtrar lo ya comprado
        bought = matrix.loc[user_id]
        final_recs_ids = recommendations[bought == 0].head(n).index.tolist()
        
        if not final_recs_ids:
             return self._cold_start_recommendations(conn, n)
             
        # Obtener detalles de los items recomendados
        query_items = "SELECT id, name, attributes FROM items WHERE id IN %s"
        df_items = pd.read_sql(query_items, conn, params=(tuple(final_recs_ids),))
        
        # APLICAR MISMA CORRECCIÓN DE LIMPIEZA
        if not df_items.empty:
            df_items['attributes'] = df_items['attributes'].apply(self._parse_attributes)
            df_items['id'] = pd.to_numeric(df_items['id'], errors='coerce').fillna(0).astype(int)
            
        return df_items.to_dict(orient='records')
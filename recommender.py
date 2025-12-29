import logging
import pandas as pd
import json
import unicodedata
from sklearn.metrics.pairwise import cosine_similarity
from database import get_db_connection

logger = logging.getLogger(__name__)  # logger for debug/info

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
                return self._cold_start_recommendations(conn, n, user_id)
            
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
            logger.debug("Buscando por géneros: %s", preferred_genres)

            # 1) Si existe columna 'genre' en la tabla items, usarla (más eficiente)
            try:
                cur = conn.cursor()
                cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'items' AND column_name = 'genre'")
                has_genre_col = cur.fetchone() is not None
            except Exception as e:
                logger.exception("Error comprobando columna 'genre': %s", e)
                has_genre_col = False

            df = pd.DataFrame()

            if has_genre_col:
                try:
                    # normalizar preferred_genres a minúsculas para comparar con lower(i.genre)
                    prefs_norm = [self._normalize_text(g) for g in preferred_genres]

                    # Hacemos consultas por género y combinamos de forma round-robin para asegurar cobertura
                    per_genre_rows = {g: [] for g in prefs_norm}
                    for g in prefs_norm:
                        # split into tokens and use ILIKE on tokens to avoid mismatch due to accents
                        tokens = [t for t in g.split() if t]
                        like_clauses = []
                        params_q = []
                        for t in tokens:
                            like_clauses.append("lower(i.genre) ILIKE %s")
                            params_q.append(f"%{t}%")
                            like_clauses.append("lower(i.attributes ->> 'genre') ILIKE %s")
                            params_q.append(f"%{t}%")
                        if not like_clauses:
                            per_genre_rows[g] = []
                            continue
                        where_clause = '(' + ' OR '.join(like_clauses) + ')'
                        q = f"""
                            SELECT i.id, i.name, i.genre, i.attributes
                            FROM items i
                            LEFT JOIN preferences p ON i.id = p.item_id
                            WHERE {where_clause}
                            GROUP BY i.id, i.name, i.genre, i.attributes
                            ORDER BY COUNT(p.id) DESC
                            LIMIT %s
                        """
                        params_q.append(n)
                        try:
                            logger.debug("Querying genre '%s' with tokens %s", g, tokens)
                            cur.execute(q, tuple(params_q))
                            rows_g = cur.fetchall()
                            per_genre_rows[g] = rows_g if rows_g else []
                            logger.debug("Found %s rows for genre token '%s'", len(per_genre_rows[g]), g)
                        except Exception as e:
                            logger.exception("Error en consulta por género %s: %s", g, e)

                    # Intercalar resultados por género para asegurar que todas las preferencias estén representadas
                    interleaved = []
                    pointers = {g: 0 for g in prefs_norm}
                    exhausted = False
                    while len(interleaved) < n and not exhausted:
                        exhausted = True
                        for g in prefs_norm:
                            rows_g = per_genre_rows.get(g, [])
                            idx = pointers.get(g, 0)
                            if idx < len(rows_g):
                                interleaved.append(rows_g[idx])
                                pointers[g] = idx + 1
                                exhausted = False
                                if len(interleaved) >= n:
                                    break
                    if interleaved:
                        # Si no llegamos a n, rellenar con populares globales excluyendo los ya seleccionados
                        if len(interleaved) < n:
                            existing_ids = [r['id'] if isinstance(r, dict) else r[0] for r in interleaved]
                            needed = n - len(interleaved)
                            try:
                                query_more = """
                                    SELECT i.id, i.name, i.genre, i.attributes
                                    FROM items i
                                    LEFT JOIN preferences p ON i.id = p.item_id
                                    WHERE NOT (i.id = ANY(%s))
                                    GROUP BY i.id, i.name, i.genre, i.attributes
                                    ORDER BY COUNT(p.id) DESC
                                    LIMIT %s
                                """
                                cur.execute(query_more, (existing_ids, needed))
                                more = cur.fetchall()
                                if more:
                                    # append non-duplicates
                                    for m in more:
                                        mid = m['id'] if isinstance(m, dict) else m[0]
                                        if mid not in existing_ids:
                                            interleaved.append(m)
                                            existing_ids.append(mid)
                                            if len(interleaved) >= n:
                                                break
                            except Exception as e:
                                logger.exception("Error fetching supplement popular items: %s", e)
                        df = pd.DataFrame(interleaved[:n])
                        logger.debug("Genre column round-robin returned %s rows (after supplement)", df.shape[0])
                    else:
                        df = pd.DataFrame()
                        logger.debug("Genre column round-robin returned 0 rows")
                except Exception as e:
                    logger.exception("Error en procesamiento por columna 'genre': %s", e)

            # 2) Si no hay columna 'genre' o la consulta no devolvió filas, intentar JSON attribute 'genre'
            if df.empty:
                try:
                    # normalizar preferred_genres para comparar con lower(attributes ->> 'genre')
                    prefs_norm = [self._normalize_text(g) for g in preferred_genres]

                    per_genre_rows = {g: [] for g in prefs_norm}
                    for g in prefs_norm:
                        tokens = [t for t in g.split() if t]
                        like_clauses = []
                        params_q = []
                        for t in tokens:
                            like_clauses.append("lower(i.attributes ->> 'genre') ILIKE %s")
                            params_q.append(f"%{t}%")
                            like_clauses.append("lower(i.genre) ILIKE %s")
                            params_q.append(f"%{t}%")
                        if not like_clauses:
                            per_genre_rows[g] = []
                            continue
                        where_clause = '(' + ' OR '.join(like_clauses) + ')'
                        q = f"""
                            SELECT i.id, i.name, (i.attributes ->> 'genre') AS genre, i.attributes
                            FROM items i
                            LEFT JOIN preferences p ON i.id = p.item_id
                            WHERE {where_clause}
                            GROUP BY i.id, i.name, genre, i.attributes
                            ORDER BY COUNT(p.id) DESC
                            LIMIT %s
                        """
                        params_q.append(n)
                        try:
                            logger.debug("Querying JSON-genre '%s' with tokens %s", g, tokens)
                            cur.execute(q, tuple(params_q))
                            rows_g = cur.fetchall()
                            per_genre_rows[g] = rows_g if rows_g else []
                            logger.debug("Found %s rows for JSON-genre token '%s'", len(per_genre_rows[g]), g)
                        except Exception as e:
                            logger.exception("Error en consulta JSON-genre %s: %s", g, e)

                    # Intercalar resultados por género para asegurar que todas las preferencias estén representadas
                    interleaved = []
                    pointers = {g: 0 for g in prefs_norm}
                    exhausted = False
                    while len(interleaved) < n and not exhausted:
                        exhausted = True
                        for g in prefs_norm:
                            rows_g = per_genre_rows.get(g, [])
                            idx = pointers.get(g, 0)
                            if idx < len(rows_g):
                                interleaved.append(rows_g[idx])
                                pointers[g] = idx + 1
                                exhausted = False
                                if len(interleaved) >= n:
                                    break
                    if interleaved:
                        # Si no llegamos a n, rellenar con populares globales excluyendo los ya seleccionados
                        if len(interleaved) < n:
                            existing_ids = [r['id'] if isinstance(r, dict) else r[0] for r in interleaved]
                            needed = n - len(interleaved)
                            try:
                                query_more = """
                                    SELECT i.id, i.name, (i.attributes ->> 'genre') AS genre, i.attributes
                                    FROM items i
                                    LEFT JOIN preferences p ON i.id = p.item_id
                                    WHERE NOT (i.id = ANY(%s))
                                    GROUP BY i.id, i.name, genre, i.attributes
                                    ORDER BY COUNT(p.id) DESC
                                    LIMIT %s
                                """
                                cur.execute(query_more, (existing_ids, needed))
                                more = cur.fetchall()
                                if more:
                                    for m in more:
                                        mid = m['id'] if isinstance(m, dict) else m[0]
                                        if mid not in existing_ids:
                                            interleaved.append(m)
                                            existing_ids.append(mid)
                                            if len(interleaved) >= n:
                                                break
                            except Exception as e:
                                logger.exception("Error fetching supplement popular items (JSON): %s", e)
                        df = pd.DataFrame(interleaved[:n])
                        logger.debug("JSON-genre round-robin returned %s rows (after supplement)", df.shape[0])
                    else:
                        df = pd.DataFrame()
                        logger.debug("JSON-genre round-robin returned 0 rows")
                except Exception as e:
                    logger.exception("Error en consulta por JSON 'genre': %s", e)

            # 3) Si sigue vacío, usar fallback en Python: parsear attributes y hacer matching case-insensitive
            if df.empty:
                logger.debug("No se encontraron items por SQL. Usando fallback Python para buscar por atributos (texto libre).")
                try:
                    cur = conn.cursor()
                    cur.execute("SELECT id, name, genre, attributes FROM items")
                    rows = cur.fetchall()
                    prefs_norm = [self._normalize_text(g) for g in preferred_genres]

                    # get popularity counts
                    cur.execute("SELECT item_id, COUNT(*) AS cnt FROM preferences GROUP BY item_id")
                    rows_counts = cur.fetchall()
                    counts_map = {r['item_id']: r['cnt'] for r in rows_counts} if rows_counts else {}

                    matches = []
                    for row in rows:
                        item_id = row['id']
                        name = row.get('name') if isinstance(row, dict) else None
                        genre_val = None
                        try:
                            if isinstance(row, dict):
                                genre_val = row.get('genre')
                        except Exception:
                            genre_val = None
                        attr = row['attributes'] if isinstance(row, dict) else None
                        parsed = None
                        try:
                            if isinstance(attr, str):
                                parsed = json.loads(attr.replace("'", '"'))
                            else:
                                parsed = attr
                        except Exception:
                            parsed = None

                        # attempt to get genre from attributes if not present in column
                        if not genre_val and isinstance(parsed, dict):
                            genre_val = parsed.get('genre') or parsed.get('genres')

                        # flatten all text fields from attributes into one normalized string
                        flat_text = ''
                        if isinstance(parsed, dict):
                            parts = []
                            for k, v in parsed.items():
                                if isinstance(v, list):
                                    parts.extend([str(x) for x in v])
                                else:
                                    parts.append(str(v))
                            flat_text = self._normalize_text(' '.join(parts))
                        elif isinstance(attr, str):
                            flat_text = self._normalize_text(attr)

                        # compute a simple match score: number of preferred genres appearing as substring in flat_text
                        match_score = 0
                        for pg in prefs_norm:
                            if pg and pg in flat_text:
                                match_score += 1

                        if match_score > 0:
                            popularity = counts_map.get(item_id, 0)
                            matches.append({'id': item_id, 'name': name, 'genre': genre_val, 'attributes': parsed if isinstance(parsed, dict) else {}, 'popularity': popularity, 'score': match_score})

                    if matches:
                        df_matches = pd.DataFrame(matches)
                        df_matches = df_matches.sort_values(by=['score', 'popularity'], ascending=[False, False]).head(n)
                        result = []
                        for r in df_matches.to_dict(orient='records'):
                            result.append({'id': int(r['id']), 'name': r.get('name'), 'genre': r.get('genre'), 'attributes': r.get('attributes', {})})
                        logger.debug("Python fallback (texto) found %s matches", len(result))
                        return result
                    else:
                        logger.debug("Python fallback (texto) no encontró items que coincidan con preferred_genres")
                except Exception as e:
                    logger.exception("Error en fallback Python para buscar por atributos (texto): %s", e)

        # --- PASO 3: Fallback (Si el filtrado por género falló o vino vacío) ---
        if df.empty:
            logger.debug("Fallback: Buscando populares globales (sin filtro de género)")
            query_global = """
                SELECT i.id, i.name, i.genre, i.attributes 
                FROM items i
                LEFT JOIN preferences p ON i.id = p.item_id 
                GROUP BY i.id, i.name, i.genre, i.attributes
                ORDER BY COUNT(p.id) DESC
                LIMIT %s
            """
            cur = conn.cursor()
            cur.execute(query_global, (n,))
            rows = cur.fetchall()
            if rows:
                df = pd.DataFrame(rows)
                logger.debug("Global popularity query returned %s rows", df.shape[0])
            else:
                df = pd.DataFrame()
                logger.debug("Global popularity query returned 0 rows")
        
        # If we have some dataframe (from genre queries or global), normalize and return
        if not df.empty:
            try:
                df['attributes'] = df['attributes'].apply(self._parse_attributes)
                # If genre column is missing, try to extract from attributes
                if 'genre' not in df.columns:
                    df['genre'] = df['attributes'].apply(lambda a: a.get('genre') if isinstance(a, dict) and 'genre' in a else None)
                # Try to coerce id to int but fallback to original if coercion fails
                try:
                    df['id'] = pd.to_numeric(df['id'], errors='coerce').fillna(0).astype(int)
                    df = df[df['id'] > 0]
                except Exception:
                    pass
                return df.to_dict(orient='records')
            except Exception as e:
                logger.exception("Error procesando resultados finales: %s", e)
                return []
        return []

    def _normalize_text(self, s):
        if s is None:
            return ''
        try:
            if not isinstance(s, str):
                s = str(s)
            nfkd = unicodedata.normalize('NFKD', s)
            only_ascii = nfkd.encode('ASCII', 'ignore').decode('ASCII')
            return only_ascii.lower().strip()
        except Exception:
            return str(s).lower().strip()

    def _collaborative_recommendations(self, conn, user_id, n):
        query = "SELECT user_id, item_id, value FROM preferences"
        cur = conn.cursor()
        cur.execute(query)
        rows = cur.fetchall()
        if rows:
            df_all = pd.DataFrame(rows)
        else:
            df_all = pd.DataFrame()

        # Crear matriz User-Item
        try:
            if not df_all.empty:
                matrix = df_all.pivot_table(index='user_id', columns='item_id', values='value').fillna(0)
            else:
                matrix = pd.DataFrame()
        except Exception as e:
            logger.exception("Error creando matrix user-item: %s", e)
            matrix = pd.DataFrame()

        if matrix.empty or user_id not in matrix.index:
            return self._cold_start_recommendations(conn, n, user_id)

        # Calcular similitud
        sim_matrix = cosine_similarity(matrix)
        sim_df = pd.DataFrame(sim_matrix, index=matrix.index, columns=matrix.index)
        
        # Encontrar usuarios similares
        similar_users = sim_df[user_id].sort_values(ascending=False)[1:6].index
        
        if len(similar_users) == 0:
             return self._cold_start_recommendations(conn, n, user_id)

        # Promediar gustos de similares
        recommendations = matrix.loc[similar_users].mean()
        # limpiar NaNs y valores no positivos
        recommendations = recommendations.dropna()
        recommendations = recommendations[recommendations > 0]

        if recommendations.empty:
            return self._cold_start_recommendations(conn, n, user_id)

        # Filtrar lo ya comprado y obtener un conjunto más amplio de candidatos (para permitir filtrado por género)
        bought = matrix.loc[user_id]
        candidate_ids = recommendations[bought == 0].sort_values(ascending=False).head(max(n * 3, n)).index.tolist()

        if not candidate_ids:
            return self._cold_start_recommendations(conn, n, user_id)

        # Obtener detalles de los items candidatos (incluyendo genre de la tabla)
        query_items = "SELECT id, name, genre, attributes FROM items WHERE id = ANY(%s)"
        cur.execute(query_items, (candidate_ids,))
        rows_items = cur.fetchall()
        if rows_items:
            df_items = pd.DataFrame(rows_items)
        else:
            df_items = pd.DataFrame()
        logger.debug("Fetched %s candidate items for ids: %s", 0 if df_items is None else getattr(df_items, 'shape', 'unknown'), candidate_ids)

        # Normalizar y parsear atributos y normalizar genre
        if not df_items.empty:
            df_items['attributes'] = df_items['attributes'].apply(self._parse_attributes)
            # ensure genre is present and normalized
            if 'genre' in df_items.columns:
                df_items['genre_norm'] = df_items['genre'].apply(lambda x: self._normalize_text(x) if x is not None else '')
            else:
                df_items['genre_norm'] = ''
            try:
                df_items['id'] = pd.to_numeric(df_items['id'], errors='coerce').fillna(0).astype(int)
                df_items = df_items[df_items['id'] > 0]
            except Exception:
                pass

        # Obtener géneros preferidos del usuario (si existen)
        preferred_genres = []
        try:
            cur.execute("SELECT preferred_genres FROM users WHERE id = %s", (user_id,))
            urow = cur.fetchone()
            if urow and urow['preferred_genres']:
                pdata = urow['preferred_genres']
                preferred_genres = json.loads(pdata) if isinstance(pdata, str) else pdata
        except Exception as e:
            logger.debug("No se pudo obtener preferred_genres para user %s: %s", user_id, e)

        prefs_norm = [self._normalize_text(g) for g in preferred_genres] if preferred_genres else []

        # Obtener puntuaciones colaborativas y popularidad para candidatos
        coll_scores = {}
        try:
            series_idx = recommendations.index
            for iid in df_items['id'].tolist():
                try:
                    coll_scores[iid] = float(recommendations.loc[iid]) if iid in series_idx else 0.0
                except Exception:
                    coll_scores[iid] = 0.0
        except Exception:
            pass

        pop_map = {}
        try:
            if not df_items.empty:
                cur.execute("SELECT item_id, COUNT(*) AS cnt FROM preferences WHERE item_id = ANY(%s) GROUP BY item_id", (df_items['id'].tolist(),))
                rows_cnt = cur.fetchall()
                if rows_cnt:
                    for r in rows_cnt:
                        pop_map[r['item_id']] = r['cnt']
        except Exception:
            pass

        # Calcular match score con los preferred_genres (si los hay)
        def _flatten_attributes_to_text(attr_dict):
            if not isinstance(attr_dict, dict):
                return self._normalize_text(str(attr_dict) if attr_dict else '')
            parts = []
            for k, v in attr_dict.items():
                if isinstance(v, list):
                    parts.extend([str(x) for x in v])
                else:
                    parts.append(str(v))
            return self._normalize_text(' '.join(parts))

        match_scores = {}
        for iid, row in (df_items.set_index('id').to_dict(orient='index')).items():
            # Primero intentar match por columna genre (más fiable)
            score = 0
            g = ''
            try:
                g = self._normalize_text(row.get('genre') or row.get('genre_norm') or '')
            except Exception:
                g = ''
            if prefs_norm and g and g in prefs_norm:
                score = 2  # dar peso mayor al match directo de columna
            else:
                # fallback: match por texto en attributes
                flat = _flatten_attributes_to_text(row.get('attributes', {}))
                for pg in prefs_norm:
                    if pg and pg in flat:
                        score += 1
            match_scores[iid] = score

        # Añadir columnas temporales y ordenar: priorizar match_score, luego colaborative score, luego popularidad
        if not df_items.empty:
            df_items['match_score'] = df_items['id'].apply(lambda x: match_scores.get(x, 0))
            df_items['coll_score'] = df_items['id'].apply(lambda x: coll_scores.get(x, 0.0))
            df_items['popularity'] = df_items['id'].apply(lambda x: pop_map.get(x, 0))

            # Si el usuario tiene preferred_genres pero NINGÚN candidato colaborativo coincide, caemos a cold-start priorizando géneros
            if prefs_norm and df_items['match_score'].sum() == 0:
                logger.debug("No collaborative candidates match preferred_genres; usando cold-start con prioridad de géneros")
                return self._cold_start_recommendations(conn, n, user_id)

            # Si hay preferred_genres, EXIGIMOS que las recomendaciones devueltas coincidan con esos géneros cuando sea posible
            if prefs_norm and df_items['match_score'].sum() > 0:
                matched = df_items[df_items['match_score'] > 0].copy()
                matched = matched.sort_values(by=['match_score', 'coll_score', 'popularity'], ascending=[False, False, False])

                # Si tenemos suficientes matches, devolvemos solo esos (hasta n)
                if not matched.empty:
                    # Agrupar por género normalizado y hacer selección round-robin para cubrir todos los géneros preferidos
                    groups = {}
                    for gid, r in matched.set_index('id').to_dict(orient='index').items():
                        g = self._normalize_text(r.get('genre') or r.get('genre_norm') or '')
                        if g not in groups:
                            groups[g] = []
                        groups[g].append((gid, r))

                    result = []
                    # Iterar sobre la lista de géneros preferidos primero (asegurar orden del usuario)
                    prefs_order = prefs_norm if prefs_norm else list(groups.keys())
                    pointers = {g:0 for g in prefs_order}
                    exhausted = False
                    while len(result) < n and not exhausted:
                        exhausted = True
                        for g in prefs_order:
                            bucket = groups.get(g, [])
                            idx = pointers.get(g, 0)
                            if idx < len(bucket):
                                gid, rowdata = bucket[idx]
                                result.append(rowdata)
                                pointers[g] = idx + 1
                                exhausted = False
                                if len(result) >= n:
                                    break

                    # Si aún no alcanzamos n, intentar llenar con cold-start priorizando géneros
                    if len(result) < n:
                        needed = n - len(result)
                        supplement = self._cold_start_recommendations(conn, needed, user_id)
                        existing_ids = set([r['id'] for r in result])
                        appended = []
                        for s in supplement:
                            if s['id'] not in existing_ids:
                                appended.append(s)
                                existing_ids.add(s['id'])
                                if len(appended) >= needed:
                                    break
                        result.extend(appended)

                    # Si tenemos resultados, devolverlos (limpiando campos temporales si los hubiera)
                    final_list = []
                    for r in result[:n]:
                        # asegurarse que los atributos y genre estén presentes
                        item = r.copy()
                        if 'attributes' in item and not isinstance(item['attributes'], dict):
                            item['attributes'] = self._parse_attributes(item.get('attributes'))
                        if 'genre' not in item:
                            item['genre'] = item.get('genre_norm') if 'genre_norm' in item else None
                        # remover campos internos si existieran
                        item.pop('genre_norm', None)
                        item.pop('coll_score', None)
                        item.pop('match_score', None)
                        item.pop('popularity', None)
                        final_list.append(item)

                    logger.debug("Collaborative (round-robin by genre) returning %s items", len(final_list))
                    return final_list

            # Si no hay preferred_genres o no hay matches, ordenamos por colaborative score y popularidad
            df_items = df_items.sort_values(by=['coll_score', 'popularity'], ascending=[False, False])
            df_final = df_items.head(n)
            logger.debug("Collaborative: %s candidates, %s matched preferred genres, returning %s", len(df_items), int((df_items['match_score']>0).sum() if 'match_score' in df_items.columns else 0), df_final.shape[0])
            df_final = df_final.drop(columns=['match_score', 'coll_score', 'popularity'], errors='ignore')
            return df_final.to_dict(orient='records')

        # Si no hay items, caer a cold start
        return self._cold_start_recommendations(conn, n, user_id)


import psycopg2
from psycopg2.extras import RealDictCursor

def get_db_connection():
    conn = psycopg2.connect(
        host="ep-restless-silence-adji6v9i-pooler.c-2.us-east-1.aws.neon.tech",
        database="neondb",
        user="neondb_owner",
        password="npg_ME93zYOGgfTo",
        cursor_factory=RealDictCursor
    )
    return conn
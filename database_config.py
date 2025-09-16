import psycopg2
from psycopg2.extras import RealDictCursor
import os
from typing import Dict, Any
import json

DATABASE_CONFIG = {
    "host": "switchback.proxy.rlwy.net",
    "port": 42316,
    "database": "railway",
    "user": "postgres",
    "password": "VeYzFsTFjyYfYjwxPnmCfYetRwyUaWoV"
}

def get_db_connection():
    """Retorna uma conexão com o banco de dados PostgreSQL"""
    try:
        conn = psycopg2.connect(**DATABASE_CONFIG)
        return conn
    except Exception as e:
        print(f"Erro ao conectar com o banco de dados: {e}")
        raise

def init_database():
    """Verifica se as tabelas necessárias existem no banco de dados"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Verificar se as tabelas existem
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name IN ('athletes', 'athlete_tokens', 'investments', 'users')
        """)
        
        existing_tables = [row[0] for row in cursor.fetchall()]
        required_tables = ['athletes', 'athlete_tokens', 'investments', 'users']
        
        missing_tables = [table for table in required_tables if table not in existing_tables]
        
        if missing_tables:
            print(f"Aviso: Tabelas necessárias não encontradas: {missing_tables}")
        else:
            print("Todas as tabelas necessárias estão presentes no banco de dados!")
        
        conn.commit()
        
    except Exception as e:
        conn.rollback()
        print(f"Erro ao verificar banco de dados: {e}")
        raise
    finally:
        cursor.close()
        conn.close()

def execute_query(query: str, params: tuple = None, fetch: bool = True):
    """Executa uma query no banco de dados"""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        cursor.execute(query, params)
        
        if fetch:
            result = cursor.fetchall()
            conn.commit()
            return [dict(row) for row in result]
        else:
            conn.commit()
            return cursor.rowcount
            
    except Exception as e:
        conn.rollback()
        print(f"Erro ao executar query: {e}")
        raise
    finally:
        cursor.close()
        conn.close()

def execute_single_query(query: str, params: tuple = None):
    """Executa uma query que retorna um único resultado"""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        cursor.execute(query, params)
        result = cursor.fetchone()
        conn.commit()
        return dict(result) if result else None
        
    except Exception as e:
        conn.rollback()
        print(f"Erro ao executar query: {e}")
        raise
    finally:
        cursor.close()
        conn.close()
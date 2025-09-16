#!/usr/bin/env python3
"""
Script para inicializar o banco de dados PostgreSQL
"""

from database_config import init_database

if __name__ == "__main__":
    print("Inicializando banco de dados...")
    try:
        init_database()
        print("✅ Banco de dados inicializado com sucesso!")
    except Exception as e:
        print(f"❌ Erro ao inicializar banco de dados: {e}")
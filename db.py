"""
Handles the MySQL connection and running validated, read-only queries.
Always connects using the restricted app_readonly user -- never root --
so even a bug here can't touch anything beyond candidates_masked.
"""

import mysql.connector
from mysql.connector import Error as MySQLError
import config


def get_connection():
    return mysql.connector.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        database=config.DB_NAME,
    )


def run_query(sql: str):
    """
    Runs a (pre-validated) SELECT query and returns (column_names, rows).
    Raises the underlying MySQLError if something goes wrong (e.g. the
    restricted user genuinely lacks permission -- this is expected to
    happen if the LLM ever tries to sneak past validate_sql somehow, and
    it's fine for it to fail loudly here).
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchall()
        return columns, rows
    finally:
        conn.close()

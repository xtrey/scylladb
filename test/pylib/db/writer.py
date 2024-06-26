import logging
import sqlite3
from typing import Dict, List


create_table = """CREATE TABLE IF NOT EXISTS {table_name} (
                id INTEGER PRIMARY KEY, 
                test_name TEXT, 
                architecture text NOT NULL, 
                mode TEXT, 
                cpu_usage_user INTEGER, 
                cpu_usage_system INTEGER, 
                memory_usage_highest INTEGER
        );"""


class SQLiteWriter:

    __instance = None

    def __init__(self, database_path, table_name):
        """
        Initializes the SQLWriter object.

        Args:
            database_path: Path to the SQLite database file.
            table_name: Name of the table where data will be written.
        """
        if SQLiteWriter.__instance is not None:
            raise Exception("This class is a singleton! Use the get_instance() method.")
        else:
            self.conn = sqlite3.connect(database_path)
            self.cursor = self.conn.cursor()
            self.table_name = table_name
            self.conn.cursor().execute(create_table.format(table_name=table_name)).connection.commit()
            SQLiteWriter.__instance = self

    def write_row(self, data: Dict) -> None:
        """
        Inserts a single row of data into the specified table.

        Args:
            data: A dictionary where keys are column names and values are data to insert.
        """
        logging.getLogger().log(level=logging.ERROR, msg='Inserting data into table')
        columns = ', '.join(data.keys())
        placeholders = ', '.join(['?'] * len(data))
        values = tuple(data.values())

        sql_query = f"INSERT INTO {self.table_name} ({columns}) VALUES ({placeholders})"
        self.cursor.execute(sql_query, values)
        self.conn.commit()

    def write_multiple_rows(self, data_list: List[Dict]) -> None:
        """
        Inserts multiple rows of data into the specified table.

        Args:
            data_list: A list of dictionaries, each representing a row of data.
        """
        for data in data_list:
            self.write_row(data)

    # def __del__(self):
    #     """
    #     Closes the database connection when the object is deleted.
    #     """
    #     self.conn.close()

    @classmethod
    def get_instance(cls, database_path, table_name):
        if SQLiteWriter.__instance is None:
            SQLiteWriter(database_path, table_name)
        return SQLiteWriter.__instance
        

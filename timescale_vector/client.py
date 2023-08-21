# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/00_vector.ipynb.

# %% auto 0
__all__ = ['SEARCH_RESULT_ID_IDX', 'SEARCH_RESULT_METADATA_IDX', 'SEARCH_RESULT_CONTENTS_IDX', 'SEARCH_RESULT_EMBEDDING_IDX',
           'SEARCH_RESULT_DISTANCE_IDX', 'QueryBuilder', 'Async', 'Sync']

# %% ../nbs/00_vector.ipynb 6
import asyncpg
import uuid
from pgvector.asyncpg import register_vector
from typing import (List, Optional)
import json 

# %% ../nbs/00_vector.ipynb 7
SEARCH_RESULT_ID_IDX = 0
SEARCH_RESULT_METADATA_IDX = 1
SEARCH_RESULT_CONTENTS_IDX = 2
SEARCH_RESULT_EMBEDDING_IDX = 3
SEARCH_RESULT_DISTANCE_IDX = 4

# %% ../nbs/00_vector.ipynb 8
class QueryBuilder:
    def __init__(
        self,
        table_name: str,
        num_dimensions: int,
        distance_type: str = 'cosine') -> None:
        """
        Initializes a base Vector object to generate queries for vector clients.

        Args:
            table_name (str): The name of the table.
            num_dimensions (int): The number of dimensions for the embedding vector.
            distance_type (str, optional): The distance type for indexing. Default is 'cosine' or '<=>'.
        """
        self.table_name = table_name
        self.num_dimensions = num_dimensions
        if distance_type == 'cosine' or distance_type == '<=>':
            self.distance_type = '<=>'
        elif distance_type == 'euclidean' or distance_type == '<->' or distance_type == 'l2':
            self.distance_type = '<->'
        else:
            raise ValueError(f"unrecognized distance_type {distance_type}")

    def _quote_ident(self, ident):
        """
        Quotes an identifier to prevent SQL injection.

        Args:
            ident (str): The identifier to be quoted.

        Returns:
            str: The quoted identifier.
        """
        return '"{}"'.format(ident.replace('"', '""'))

    def get_row_exists_query(self):
        """
        Generates a query to check if any rows exist in the table.

        Returns:
            str: The query to check for row existence.
        """
        return "SELECT 1 FROM {table_name} LIMIT 1".format(table_name=self._quote_ident(self.table_name))

    #| export
    def get_upsert_query(self):
        """
        Generates an upsert query.

        Returns:
            str: The upsert query.
        """
        return "INSERT INTO {table_name} (id, metadata, contents, embedding) VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING".format(table_name=self._quote_ident(self.table_name))

    def get_approx_count_query(self):
        """
        Generate a query to find the approximate count of records in the table.

        Returns:
            str: the query.
        """
        #todo optimize with approx
        return "SELECT COUNT(*) as cnt FROM {table_name}".format(table_name=self._quote_ident(self.table_name))

    #| export
    def get_create_query(self):
        """
        Generates a query to create the tables, indexes, and extensions needed to store the vector data.

        Returns:
            str: The create table query.
        """
        return '''
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS {table_name} (
    id UUID PRIMARY KEY,
    metadata JSONB,
    contents TEXT,
    embedding VECTOR({dimensions})
);

CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} USING GIN(metadata jsonb_path_ops);
'''.format(table_name=self._quote_ident(self.table_name), index_name=self._quote_ident(self.table_name+"_meta_idx"), dimensions=self.num_dimensions)

    def _get_embedding_index_name(self):
        return self._quote_ident(self.table_name+"_embedding_idx")
    
    def drop_embedding_index_query(self):
        return "DROP INDEX IF EXISTS {index_name};".format(index_name=self._get_embedding_index_name())

    def delete_all_query(self):
        return "TRUNCATE {table_name};".format(table_name=self._quote_ident(self.table_name))
       
    def create_ivfflat_index_query(self, num_records):
        """
        Generates an ivfflat index creation query.

        Args:
            num_records (int): The number of records in the table.

        Returns:
            str: The index creation query.
        """
        column_name = "embedding" 

        index_method = "invalid"
        if self.distance_type == "<->":
            index_method = "vector_l2_ops"
        elif self.distance_type == "<#>":
            index_method = "vector_ip_ops"
        elif self.distance_type == "<=>":
            index_method = "vector_cosine_ops"
        else:
            raise ValueError(f"unrecognized operator {query_operator}")
        
        num_lists = num_records / 1000
        if num_lists < 10:
            num_lists = 10
        if num_records > 1000000:
            num_lists = math.sqrt(num_records)

        return "CREATE INDEX {index_name} ON {table_name} USING ivfflat ({column_name} {index_method}) WITH (lists = {num_lists});"\
        .format(index_name=self._get_embedding_index_name(), table_name=self._quote_ident(self.table_name), column_name=self._quote_ident(column_name), index_method=index_method, num_lists=num_lists)

    def search_query(self, query_embedding: List[float], k: int=10, filter: Optional[dict] = None):
        """
        Generates a similarity query.

        Args:
            query_embedding (List[float]): The query embedding vector.
            k (int, optional): The number of nearest neighbors to retrieve. Default is 10.
            filter (Optional[dict], optional): A filter for metadata. Default is None.

        Returns:
            Tuple[str, List]: A tuple containing the query and parameters.
        """
        params = []
        distance = "embedding {op} ${index}".format(op=self.distance_type, index=len(params)+1)
        params = params + [query_embedding]
        
        where = "TRUE"
        if filter != None:
            where = "metadata @> ${index}".format(index=len(params)+1)
            json_object = json.dumps(filter)
            params = params + [json_object]
        query = '''
        SELECT
            id, metadata, contents, embedding, {distance} as distance
        FROM
           {table_name}
        WHERE 
           {where}
        ORDER BY {distance} ASC
        LIMIT {k}
        '''.format(distance=distance, where=where, table_name=self._quote_ident(self.table_name), k=k)
        return (query, params)

# %% ../nbs/00_vector.ipynb 11
class Async(QueryBuilder):
    def __init__(
        self,
        connection_string: str,
        table_name: str,
        num_dimensions: int,
        distance_type: str = 'cosine') -> None:
            """
            Initializes a async client for storing vector data.
    
            Args:
                connection_string (str): The connection string for the database.
                table_name (str): The name of the table.
                num_dimensions (int): The number of dimensions for the embedding vector.
                distance_type (str, optional): The distance type for indexing. Default is 'cosine' or '<=>'.
            """
            self.builder = QueryBuilder(table_name,num_dimensions, distance_type)
            self.connection_string = connection_string
            self.pool = None
            
    async def connect(self):
        """
        Establishes a connection to a PostgreSQL database using asyncpg.

        Returns:
            asyncpg.Connection: The established database connection.
        """
        if self.pool == None:
            async def init(conn):
                await register_vector(conn)
            self.pool = await asyncpg.create_pool(dsn=self.connection_string, init=init)
        return self.pool.acquire()

    async def table_is_empty(self):
        """
        Checks if the table is empty.

        Returns:
            bool: True if the table is empty, False otherwise.
        """
        query = self.builder.get_row_exists_query()
        async with await self.connect() as pool:
            rec = await pool.fetchrow(query)
            return rec == None

    def _convert_record_meta_to_json(item):
        if not isinstance(item[1], dict):
            raise ValueError("Cannot mix dictionary and string metadata fields in the same upsert")
        return (item[0], json.dumps(item[1]), item[2], item[3])


    async def upsert(self, records):
        """
        Performs upsert operation for multiple records.

        Args:
            records: Records to upsert.

        Returns:
            None
        """
        if isinstance(records[0][1], dict):
            records = list(map(lambda item: Async._convert_record_meta_to_json(item), records))
        query = self.builder.get_upsert_query()
        async with await self.connect() as pool:
            await pool.executemany(query, records)

    async def create_tables(self):
        """
        Creates necessary tables.

        Returns:
            None
        """
        query = self.builder.get_create_query()
        async with await self.connect() as pool:
            await pool.execute(query)

    async def delete_all(self, drop_index=True):
        """
        Deletes all data. Also drops the index if `drop_index` is true.

        Returns:
            None
        """
        if drop_index:
            await self.drop_embedding_index();
        query = self.builder.delete_all_query()
        async with await self.connect() as pool:
            await pool.execute(query)

    async def _get_approx_count(self):
        """
        Retrieves an approximate count of records in the table.

        Returns:
            int: Approximate count of records.
        """
        query = self.builder.get_approx_count_query()
        async with await self.connect() as pool:
            rec = await pool.fetchrow(query)
            return rec[0]

    async def drop_embedding_index(self):
        """
        Drop any index on the emedding

        Returns:
            None
        """
        query = self.builder.drop_embedding_index_query()
        async with await self.connect() as pool:
            await pool.execute(query)
    
    async def create_ivfflat_index(self, num_records=None):
        """
        Creates an ivfflat index for the table.

        Args:
            num_records (int, optional): The number of records. If None, it's calculated. Default is None.

        Returns:
            None
        """
        if num_records == None:
            num_records = await self._get_approx_count()
        query = self.builder.create_ivfflat_index_query(num_records)
        async with await self.connect() as pool:
            await pool.execute(query)

    async def search(self, 
                     query_embedding: List[float], # vector to search for
                     k: int=10, # The number of nearest neighbors to retrieve. Default is 10.
                     filter: Optional[dict] = None): # A filter for metadata. Default is None.
        """
        Retrieves similar records using a similarity query.

        Returns:
            List: List of similar records.
        """
        (query, params) = self.builder.search_query(query_embedding, k, filter)
        async with await self.connect() as pool:
            return await pool.fetch(query, *params)

# %% ../nbs/00_vector.ipynb 19
import psycopg2.pool
from contextlib import contextmanager
import psycopg2.extras
import pgvector.psycopg2
import numpy as np
import re

# %% ../nbs/00_vector.ipynb 20
class Sync:
    translated_queries = {}
    
    def __init__(
        self,
        connection_string: str,
        table_name: str,
        num_dimensions: int,
        distance_type: str = 'cosine') -> None:
            self.builder = QueryBuilder(table_name,num_dimensions, distance_type)
            self.connection_string = connection_string
            self.pool = None
            psycopg2.extras.register_uuid()

    
    @contextmanager
    def connect(self):
        """
        Establishes a connection to a PostgreSQL database using psycopg2 and allows it's
        use in a context manager.
        """
        if self.pool == None:
            self.pool = psycopg2.pool.SimpleConnectionPool(1, 10, dsn=self.connection_string)
        
        connection = self.pool.getconn()
        pgvector.psycopg2.register_vector(connection)
        try:
            yield connection
            connection.commit()
        finally:            
            self.pool.putconn(connection)

    def _translate_to_pyformat(self, query_string, params):
        """
        Translates dollar sign number parameters and list parameters to pyformat strings.

        Args:
            query_string (str): The query string with parameters.
            params (list): List of parameter values.
    
        Returns:
            str: The query string with translated pyformat parameters.
            dict: A dictionary mapping parameter numbers to their values.
        """
        
        translated_params = {}
        if params != None:
            for idx, param in enumerate(params):
                translated_params[str(idx+1)] = param

        if query_string in self.translated_queries:
            return self.translated_queries[query_string], translated_params

        dollar_params = re.findall(r'\$[0-9]+', query_string) 
        translated_string = query_string 
        for dollar_param in dollar_params:
            param_number = int(dollar_param[1:])  # Extract the number after the $
            if params != None:
                pyformat_param = '%s' if param_number == 0 else f'%({param_number})s'
            else:
                pyformat_param = '%s'
            translated_string = translated_string.replace(dollar_param, pyformat_param)

        self.translated_queries[query_string] = translated_string 
        return self.translated_queries[query_string], translated_params
        
    def table_is_empty(self):
        """
        Checks if the table is empty.

        Returns:
            bool: True if the table is empty, False otherwise.
        """
        query = self.builder.get_row_exists_query()
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                rec = cur.fetchone()
                return rec == None

    def _convert_record_meta_to_json(item):
        if not isinstance(item[1], dict):
            raise ValueError("Cannot mix dictionary and string metadata fields in the same upsert")
        return (item[0], json.dumps(item[1]), item[2], item[3])
    
    def upsert(self, records):
        """
        Performs upsert operation for multiple records.

        Args:
            records: Records to upsert.

        Returns:
            None
        """
        if isinstance(records[0][1], dict):
            records = list(map(lambda item: Async._convert_record_meta_to_json(item), records))
                    
        query = self.builder.get_upsert_query()
        query, _ = self._translate_to_pyformat(query, None)
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.executemany(query, records)

    def create_tables(self):
        """
        Creates necessary tables.

        Returns:
            None
        """
        query = self.builder.get_create_query()
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query)

    def delete_all(self, drop_index=True):
        """
        Deletes all data. Also drops the index if `drop_index` is true.

        Returns:
            None
        """
        if drop_index:
            self.drop_embedding_index();
        query = self.builder.delete_all_query()
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query)

    def _get_approx_count(self):
        """
        Retrieves an approximate count of records in the table.

        Returns:
            int: Approximate count of records.
        """
        query = self.builder.get_approx_count_query()
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                rec = cur.fetchone()
                return rec[0]

    def drop_embedding_index(self):
        """
        Drop any index on the emedding

        Returns:
            None
        """
        query = self.builder.drop_embedding_index_query()
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
    
    def create_ivfflat_index(self, num_records=None):
        """
        Creates an ivfflat index for the table.

        Args:
            num_records (int, optional): The number of records. If None, it's calculated. Default is None.

        Returns:
            None
        """
        if num_records == None:
            num_records = self._get_approx_count()
        query = self.builder.create_ivfflat_index_query(num_records)
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query)

    def search(self, query_embedding: List[float], k: int=10, filter: Optional[dict] = None):
        """
        Retrieves similar records using a similarity query.

        Args:
            query_embedding (List[float]): The query embedding vector.
            k (int, optional): The number of nearest neighbors to retrieve. Default is 10.
            filter (Optional[dict], optional): A filter for metadata. Default is None.

        Returns:
            List: List of similar records.
        """
        (query, params) = self.builder.search_query(np.array(query_embedding), k, filter)
        query, params = self._translate_to_pyformat(query, params)
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return cur.fetchall()

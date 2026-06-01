from datetime import datetime

import os
import peewee
import libsql

class LibSQLDatabase(peewee.SqliteDatabase):
    def _connect(self):
        database = self.database
        env_url = os.environ.get("LIBSQL_URL")
        env_token = os.environ.get("LIBSQL_AUTH_TOKEN")
        
        if env_url:
            database = env_url
            
        auth_token = self.connect_params.get('auth_token') or env_token
        encryption_key = self.connect_params.get('encryption_key')
        tls = self.connect_params.get('tls')
        
        connect_args = {}
        if auth_token:
            connect_args['auth_token'] = auth_token
        if encryption_key:
            connect_args['encryption_key'] = encryption_key
        if tls is not None:
            connect_args['tls'] = tls
            
        return libsql.connect(database, isolation_level=None, **connect_args)

db_path = os.environ.get("LIBSQL_URL") or 'data/feed_database.db'

# Automatically create the directory for the database if it is a local path
if db_path and not (db_path.startswith("libsql://") or db_path.startswith("http://") or db_path.startswith("https://") or db_path == ":memory:"):
    dir_name = os.path.dirname(db_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)

db = LibSQLDatabase(db_path)



class BaseModel(peewee.Model):
    class Meta:
        database = db


class LibSQLDateTimeField(peewee.DateTimeField):
    def db_value(self, value):
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.strftime('%Y-%m-%d %H:%M:%S.%f')
        return super().db_value(value)


class Post(BaseModel):
    uri = peewee.CharField(index=True)
    cid = peewee.CharField()
    reply_parent = peewee.CharField(null=True, default=None)
    reply_root = peewee.CharField(null=True, default=None)
    indexed_at = LibSQLDateTimeField(default=datetime.utcnow)



class SubscriptionState(BaseModel):
    service = peewee.CharField(unique=True)
    cursor = peewee.BigIntegerField()


if db.is_closed():
    db.connect()
    db.create_tables([Post, SubscriptionState])

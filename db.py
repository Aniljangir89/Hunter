"""
Job Hunter — MongoDB Connection Module
"""
import os
from pymongo import MongoClient

_client = None
_db = None


def get_db():
    """Get the MongoDB database instance (lazy singleton)."""
    global _client, _db
    if _db is None:
        uri = os.environ.get('MONGODB_URI', '')
        if not uri:
            raise RuntimeError(
                'MONGODB_URI environment variable is not set. '
                'Set it to your MongoDB Atlas connection string.'
            )
        _client = MongoClient(uri)
        _db = _client['job_hunter']
    return _db


def get_contacts_collection():
    """Get the contacts collection."""
    return get_db()['contacts']


def get_counters_collection():
    """Get the counters collection (for auto-increment IDs)."""
    return get_db()['counters']


def get_next_id():
    """Get the next auto-increment ID for contacts."""
    counters = get_counters_collection()
    result = counters.find_one_and_update(
        {'_id': 'contact_id'},
        {'$inc': {'seq': 1}},
        upsert=True,
        return_document=True
    )
    return result['seq']

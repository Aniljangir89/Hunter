"""
One-time migration script: Upload data.json into MongoDB Atlas.

Usage:
    set MONGODB_URI=mongodb+srv://user:pass@cluster0.xxxxx.mongodb.net/...
    python migrate_to_mongo.py
"""
import json
import os
import sys

import certifi
from pymongo import MongoClient


def migrate():
    uri = os.environ.get('MONGODB_URI', '')
    if not uri:
        print("ERROR: Set the MONGODB_URI environment variable first.")
        print("  Example (PowerShell):")
        print('  $env:MONGODB_URI = "mongodb+srv://user:pass@cluster.xxxxx.mongodb.net/?retryWrites=true&w=majority"')
        sys.exit(1)

    # Load local data
    data_file = 'data.json'
    if not os.path.exists(data_file):
        print(f"ERROR: {data_file} not found in current directory.")
        sys.exit(1)

    with open(data_file, 'r', encoding='utf-8') as f:
        records = json.load(f)

    print(f"Loaded {len(records)} records from {data_file}")

    # Connect to MongoDB
    print("Connecting to MongoDB Atlas...")
    client = MongoClient(uri, tlsCAFile=certifi.where())
    db = client['job_hunter']
    col = db['contacts']

    # Check if collection already has data
    existing = col.count_documents({})
    if existing > 0:
        response = input(
            f"Collection already has {existing} documents. "
            f"Drop and re-import? (yes/no): "
        ).strip().lower()
        if response != 'yes':
            print("Aborted.")
            sys.exit(0)
        col.drop()
        print("Dropped existing collection.")

    # Insert records in batches
    batch_size = 500
    total = len(records)
    for i in range(0, total, batch_size):
        batch = records[i:i + batch_size]
        col.insert_many(batch)
        inserted = min(i + batch_size, total)
        print(f"  Inserted {inserted}/{total} records...")

    # Initialize auto-increment counter
    max_id = max(r['id'] for r in records) if records else 0
    db['counters'].update_one(
        {'_id': 'contact_id'},
        {'$set': {'seq': max_id}},
        upsert=True
    )
    print(f"  Set auto-increment counter to {max_id}")

    # Create indexes for performance
    col.create_index('id', unique=True)
    col.create_index('email')
    col.create_index('company')
    col.create_index('locations')
    col.create_index('email_type')
    col.create_index('validation.status')
    print("  Created indexes on: id, email, company, locations, email_type, validation.status")

    # Verify
    final_count = col.count_documents({})
    print(f"\nMigration complete! {final_count} records now in MongoDB Atlas.")
    print("   Database: job_hunter")
    print("   Collection: contacts")


if __name__ == '__main__':
    migrate()

"""
Job Hunter — HR Data Command Center
Flask Backend API Server (MongoDB Edition)
"""
import json
import os
import re
import csv
import io
import smtplib
import socket
from datetime import datetime
from threading import Thread, Lock

from flask import Flask, request, jsonify, render_template, send_file

import dns.resolver
from db import get_contacts_collection, get_next_id

app = Flask(__name__, static_folder='static', template_folder='templates')

# ─── Personal email domains ───────────────────────────────────────────
PERSONAL_DOMAINS = {
    'gmail.com', 'yahoo.com', 'yahoo.in', 'yahoo.co.in',
    'hotmail.com', 'outlook.com', 'live.com', 'msn.com',
    'rediffmail.com', 'aol.com', 'icloud.com', 'protonmail.com',
    'mail.com', 'zoho.com', 'ymail.com', 'googlemail.com'
}

# ─── City normalization map ───────────────────────────────────────────
CITY_NORMALIZE = {
    'bengaluru': 'Bangalore', 'banglore': 'Bangalore', 'bangluru': 'Bangalore',
    'bangaluru': 'Bangalore', 'blr': 'Bangalore',
    'gurgaon': 'Gurgaon', 'gurugram': 'Gurgaon',
    'noida': 'Noida', 'greater noida': 'Noida',
    'mumbai': 'Mumbai', 'bombay': 'Mumbai',
    'pune': 'Pune', 'delhi': 'Delhi', 'new delhi': 'Delhi',
    'delhi ncr': 'Delhi NCR', 'ncr': 'Delhi NCR',
    'hyderabad': 'Hyderabad', 'chennai': 'Chennai', 'madras': 'Chennai',
    'kolkata': 'Kolkata', 'calcutta': 'Kolkata',
    'jaipur': 'Jaipur', 'ahmedabad': 'Ahmedabad',
    'chandigarh': 'Chandigarh', 'lucknow': 'Lucknow', 'indore': 'Indore',
    'kochi': 'Kochi', 'cochin': 'Kochi',
    'thiruvananthapuram': 'Thiruvananthapuram', 'trivandrum': 'Thiruvananthapuram',
    'coimbatore': 'Coimbatore', 'vadodara': 'Vadodara', 'baroda': 'Vadodara',
    'remote': 'Remote', 'work from home': 'Remote', 'wfh': 'Remote',
    'pan india': 'Pan India', 'india': 'Pan India', 'across india': 'Pan India',
}


# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════

def normalize_city(city):
    """Normalize a city name."""
    return CITY_NORMALIZE.get(city.strip().lower(), city.strip().title())


def classify_email(domain):
    """Classify email as corporate, personal, or invalid."""
    if not domain:
        return 'invalid'
    if domain.lower() in PERSONAL_DOMAINS:
        return 'personal'
    return 'corporate'


def is_valid_email_syntax(email):
    """Check email syntax with regex."""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, str(email)))


def serialize_contact(doc):
    """Convert a MongoDB document to a JSON-serializable dict."""
    if doc is None:
        return None
    doc.pop('_id', None)  # Remove MongoDB ObjectId
    return doc


# ═══════════════════════════════════════════════════════════════════════
# EMAIL VALIDATION
# ═══════════════════════════════════════════════════════════════════════

def check_mx_record(domain):
    """Check if domain has valid MX records."""
    try:
        records = dns.resolver.resolve(domain, 'MX')
        mx_hosts = [str(r.exchange) for r in records]
        return True, mx_hosts
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer,
            dns.resolver.NoNameservers, dns.exception.Timeout):
        return False, []
    except Exception:
        return False, []


def check_smtp(email, mx_hosts, timeout=10):
    """
    Verify mailbox exists via SMTP RCPT TO.
    Returns: True (exists), False (rejected), None (inconclusive)
    """
    if not mx_hosts:
        return None

    for mx_host in mx_hosts[:2]:  # Try first 2 MX hosts
        mx_host = mx_host.rstrip('.')
        try:
            with smtplib.SMTP(mx_host, 25, timeout=timeout) as smtp:
                smtp.ehlo('verify.local')
                smtp.mail('verify@verify.local')
                code, _ = smtp.rcpt(email)
                if code == 250:
                    return True
                elif code == 550:
                    return False
        except (smtplib.SMTPException, socket.timeout, socket.error,
                ConnectionRefusedError, OSError):
            continue
    return None  # Inconclusive


def validate_email_full(email):
    """Run the full 3-level validation pipeline."""
    result = {
        'email': email,
        'syntax': False,
        'mx': None,
        'mx_hosts': [],
        'smtp': None,
        'status': 'invalid_syntax'
    }

    # Level 1: Syntax
    if not is_valid_email_syntax(email):
        return result
    result['syntax'] = True

    # Level 2: MX Record
    domain = email.split('@')[-1]
    mx_valid, mx_hosts = check_mx_record(domain)
    result['mx'] = mx_valid
    result['mx_hosts'] = mx_hosts

    if not mx_valid:
        result['status'] = 'no_mx'
        return result

    # Level 3: SMTP Check
    smtp_result = check_smtp(email, mx_hosts)
    result['smtp'] = smtp_result

    if smtp_result is True:
        result['status'] = 'verified'
    elif smtp_result is False:
        result['status'] = 'rejected'
    else:
        result['status'] = 'mx_valid'  # MX exists but SMTP inconclusive

    return result


# ═══════════════════════════════════════════════════════════════════════
# ROUTES — Frontend
# ═══════════════════════════════════════════════════════════════════════

@app.route('/')
def index():
    return render_template('index.html')


# ═══════════════════════════════════════════════════════════════════════
# API — Contacts CRUD
# ═══════════════════════════════════════════════════════════════════════

@app.route('/api/contacts', methods=['GET'])
def get_contacts():
    """List contacts with pagination, search, and filters."""
    col = get_contacts_collection()

    # Build MongoDB query filter
    query = {}

    # Search
    search = request.args.get('search', '').lower().strip()
    if search:
        query['$or'] = [
            {'company': {'$regex': search, '$options': 'i'}},
            {'email': {'$regex': search, '$options': 'i'}},
            {'location': {'$regex': search, '$options': 'i'}}
        ]

    # Filter by city
    city = request.args.get('city', '').strip()
    if city:
        query['locations'] = {'$regex': f'^{re.escape(city)}$', '$options': 'i'}

    # Filter by email type
    email_type = request.args.get('email_type', '').strip()
    if email_type:
        query['email_type'] = email_type

    # Filter by validation status
    val_status = request.args.get('validation_status', '').strip()
    if val_status:
        query['validation.status'] = val_status

    total = col.count_documents(query)

    # Pagination
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))
    skip = (page - 1) * per_page

    cursor = col.find(query, {'_id': 0}).skip(skip).limit(per_page)
    contacts = list(cursor)

    return jsonify({
        'contacts': contacts,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': (total + per_page - 1) // per_page
    })


@app.route('/api/contacts', methods=['POST'])
def add_contact():
    """Add a new HR contact."""
    data = request.get_json()
    company = data.get('company', '').strip()
    location = data.get('location', '').strip()
    email = data.get('email', '').strip().lower()

    if not company or not email:
        return jsonify({'error': 'Company and email are required'}), 400

    col = get_contacts_collection()

    # Check for duplicate email
    if col.find_one({'email': email}):
        return jsonify({'error': f'Email {email} already exists'}), 409

    domain = email.split('@')[-1] if '@' in email else ''
    raw_locations = [loc.strip() for loc in location.replace(',', '/').split('/') if loc.strip()]
    if not raw_locations:
        raw_locations = ['Unknown']
    normalized = [normalize_city(loc) for loc in raw_locations]

    syntax_valid = is_valid_email_syntax(email)

    new_record = {
        'id': get_next_id(),
        'company': company,
        'location': location,
        'locations': normalized,
        'email': email,
        'domain': domain,
        'email_type': classify_email(domain),
        'validation': {
            'syntax': syntax_valid,
            'mx': None,
            'smtp': None,
            'status': 'valid_syntax' if syntax_valid else 'invalid_syntax'
        },
        'added_at': datetime.now().isoformat(),
        'is_cleaned': False
    }

    col.insert_one(new_record)

    return jsonify({
        'message': 'Contact added',
        'contact': serialize_contact(new_record)
    }), 201


@app.route('/api/contacts/<int:contact_id>', methods=['PUT'])
def update_contact(contact_id):
    """Update an existing contact."""
    data = request.get_json()
    col = get_contacts_collection()

    contact = col.find_one({'id': contact_id})
    if not contact:
        return jsonify({'error': 'Contact not found'}), 404

    update_fields = {}

    if 'company' in data:
        update_fields['company'] = data['company'].strip()
    if 'location' in data:
        update_fields['location'] = data['location'].strip()
        raw_locs = [l.strip() for l in data['location'].replace(',', '/').split('/') if l.strip()]
        update_fields['locations'] = [normalize_city(l) for l in raw_locs] or ['Unknown']
    if 'email' in data:
        new_email = data['email'].strip().lower()
        # Check duplicate (excluding self)
        existing = col.find_one({'email': new_email, 'id': {'$ne': contact_id}})
        if existing:
            return jsonify({'error': f'Email {new_email} already exists'}), 409
        update_fields['email'] = new_email
        update_fields['domain'] = new_email.split('@')[-1] if '@' in new_email else ''
        update_fields['email_type'] = classify_email(update_fields['domain'])
        update_fields['validation'] = {
            'syntax': is_valid_email_syntax(new_email),
            'mx': None, 'smtp': None,
            'status': 'valid_syntax' if is_valid_email_syntax(new_email) else 'invalid_syntax'
        }

    if update_fields:
        col.update_one({'id': contact_id}, {'$set': update_fields})

    updated = col.find_one({'id': contact_id}, {'_id': 0})
    return jsonify({'message': 'Contact updated', 'contact': updated})


@app.route('/api/contacts/<int:contact_id>', methods=['DELETE'])
def delete_contact(contact_id):
    """Delete a contact."""
    col = get_contacts_collection()
    result = col.delete_one({'id': contact_id})

    if result.deleted_count == 0:
        return jsonify({'error': 'Contact not found'}), 404

    return jsonify({'message': 'Contact deleted'})


@app.route('/api/contacts/bulk-delete', methods=['POST'])
def bulk_delete():
    """Delete multiple contacts by IDs."""
    data = request.get_json()
    ids_to_delete = list(data.get('ids', []))

    col = get_contacts_collection()
    result = col.delete_many({'id': {'$in': ids_to_delete}})

    return jsonify({
        'message': f'{result.deleted_count} contacts deleted',
        'deleted': result.deleted_count
    })


# ═══════════════════════════════════════════════════════════════════════
# API — Email Validation
# ═══════════════════════════════════════════════════════════════════════

@app.route('/api/validate-email', methods=['POST'])
def validate_single_email():
    """Validate a single email address."""
    data = request.get_json()
    email = data.get('email', '').strip().lower()

    if not email:
        return jsonify({'error': 'Email is required'}), 400

    result = validate_email_full(email)

    # Update in database if this email exists
    col = get_contacts_collection()
    col.update_many(
        {'email': email},
        {'$set': {
            'validation': {
                'syntax': result['syntax'],
                'mx': result['mx'],
                'smtp': result['smtp'],
                'status': result['status']
            }
        }}
    )

    return jsonify(result)


# Bulk validation state
bulk_validation_state = {
    'running': False,
    'total': 0,
    'processed': 0,
    'results': {'verified': 0, 'mx_valid': 0, 'no_mx': 0,
                'rejected': 0, 'invalid_syntax': 0, 'error': 0}
}
bulk_lock = Lock()


def run_bulk_validation():
    """Background worker for bulk email validation."""
    global bulk_validation_state
    col = get_contacts_collection()
    records = list(col.find({}, {'_id': 0, 'id': 1, 'email': 1}))

    with bulk_lock:
        bulk_validation_state['total'] = len(records)
        bulk_validation_state['processed'] = 0
        bulk_validation_state['results'] = {
            'verified': 0, 'mx_valid': 0, 'no_mx': 0,
            'rejected': 0, 'invalid_syntax': 0, 'error': 0
        }

    for i, record in enumerate(records):
        if not bulk_validation_state['running']:
            break  # Cancelled

        try:
            result = validate_email_full(record['email'])
            col.update_one(
                {'id': record['id']},
                {'$set': {
                    'validation': {
                        'syntax': result['syntax'],
                        'mx': result['mx'],
                        'smtp': result['smtp'],
                        'status': result['status']
                    }
                }}
            )
            with bulk_lock:
                status = result['status']
                if status in bulk_validation_state['results']:
                    bulk_validation_state['results'][status] += 1
                else:
                    bulk_validation_state['results']['error'] += 1
        except Exception:
            with bulk_lock:
                bulk_validation_state['results']['error'] += 1

        with bulk_lock:
            bulk_validation_state['processed'] = i + 1

    with bulk_lock:
        bulk_validation_state['running'] = False


@app.route('/api/validate-bulk', methods=['POST'])
def start_bulk_validation():
    """Start bulk email validation in background."""
    global bulk_validation_state

    if bulk_validation_state['running']:
        return jsonify({'error': 'Bulk validation already running'}), 409

    bulk_validation_state['running'] = True
    thread = Thread(target=run_bulk_validation, daemon=True)
    thread.start()

    return jsonify({'message': 'Bulk validation started'})


@app.route('/api/validate-bulk/status', methods=['GET'])
def bulk_validation_status():
    """Get bulk validation progress."""
    with bulk_lock:
        return jsonify(bulk_validation_state)


@app.route('/api/validate-bulk/stop', methods=['POST'])
def stop_bulk_validation():
    """Stop bulk validation."""
    global bulk_validation_state
    bulk_validation_state['running'] = False
    return jsonify({'message': 'Bulk validation stopped'})


# ═══════════════════════════════════════════════════════════════════════
# API — Data Cleaning
# ═══════════════════════════════════════════════════════════════════════

@app.route('/api/clean', methods=['POST'])
def clean_data():
    """Run cleaning operations on the data."""
    data = request.get_json()
    operation = data.get('operation', '')
    col = get_contacts_collection()
    changes = []

    if operation == 'normalize_cities':
        for r in col.find({}, {'_id': 0}):
            raw_locs = [l.strip() for l in r['location'].replace(',', '/').split('/') if l.strip()]
            new_locs = [normalize_city(l) for l in raw_locs]
            if new_locs != r.get('locations', []):
                changes.append({
                    'id': r['id'],
                    'field': 'locations',
                    'old': r.get('locations', []),
                    'new': new_locs
                })
                col.update_one(
                    {'id': r['id']},
                    {'$set': {'locations': new_locs, 'is_cleaned': True}}
                )

    elif operation == 'remove_invalid_emails':
        for r in col.find({}, {'_id': 0}):
            if not is_valid_email_syntax(r['email']):
                changes.append({
                    'id': r['id'],
                    'action': 'removed',
                    'reason': 'invalid email syntax',
                    'email': r['email']
                })
                col.delete_one({'id': r['id']})

    elif operation == 'flag_personal_emails':
        for r in col.find({}, {'_id': 0}):
            old_type = r.get('email_type', '')
            new_type = classify_email(r.get('domain', ''))
            if old_type != new_type:
                changes.append({
                    'id': r['id'],
                    'field': 'email_type',
                    'old': old_type,
                    'new': new_type
                })
            col.update_one({'id': r['id']}, {'$set': {'email_type': new_type}})

    elif operation == 'trim_whitespace':
        for r in col.find({}, {'_id': 0}):
            old_company = r['company']
            new_company = ' '.join(r['company'].split())
            if old_company != new_company:
                changes.append({
                    'id': r['id'],
                    'field': 'company',
                    'old': old_company,
                    'new': new_company
                })
                col.update_one(
                    {'id': r['id']},
                    {'$set': {'company': new_company, 'is_cleaned': True}}
                )

    elif operation == 'fix_casing':
        for r in col.find({}, {'_id': 0}):
            old_company = r['company']
            new_company = r['company'].strip()
            if new_company == new_company.upper() or new_company == new_company.lower():
                new_company = new_company.title()
            if old_company != new_company:
                changes.append({
                    'id': r['id'],
                    'field': 'company',
                    'old': old_company,
                    'new': new_company
                })
                col.update_one(
                    {'id': r['id']},
                    {'$set': {'company': new_company, 'is_cleaned': True}}
                )

    elif operation == 'remove_empty_entries':
        for r in col.find({}, {'_id': 0}):
            if not r['email'] or not r['company'] or r['company'] == 'Unknown':
                changes.append({
                    'id': r['id'],
                    'action': 'removed',
                    'reason': 'empty company or email',
                    'company': r['company'],
                    'email': r['email']
                })
                col.delete_one({'id': r['id']})

    else:
        return jsonify({'error': f'Unknown operation: {operation}'}), 400

    total_records = col.count_documents({})
    return jsonify({
        'message': f'Cleaning operation "{operation}" completed',
        'changes_count': len(changes),
        'changes': changes[:100],  # Return first 100 changes for preview
        'total_records': total_records
    })


@app.route('/api/dedup', methods=['POST'])
def deduplicate():
    """Find and remove duplicate entries based on email."""
    data = request.get_json()
    preview_only = data.get('preview', True)

    col = get_contacts_collection()

    # Use aggregation to find duplicates
    pipeline = [
        {'$group': {
            '_id': {'$toLower': '$email'},
            'count': {'$sum': 1},
            'docs': {'$push': {'id': '$id', 'company': '$company',
                               'email': '$email', 'location': '$location'}}
        }},
        {'$match': {'count': {'$gt': 1}}}
    ]

    duplicates = []
    ids_to_remove = []

    for group in col.aggregate(pipeline):
        docs = group['docs']
        original = docs[0]  # Keep the first one
        for dup in docs[1:]:
            duplicates.append({
                'duplicate': dup,
                'original_id': original['id']
            })
            ids_to_remove.append(dup['id'])

    if not preview_only and ids_to_remove:
        col.delete_many({'id': {'$in': ids_to_remove}})

    records_after = col.count_documents({})

    return jsonify({
        'message': 'Deduplication ' + ('preview' if preview_only else 'applied'),
        'duplicates_found': len(duplicates),
        'duplicates': duplicates[:100],  # First 100 for preview
        'records_after': records_after,
        'applied': not preview_only
    })


# ═══════════════════════════════════════════════════════════════════════
# API — Stats & Export
# ═══════════════════════════════════════════════════════════════════════

@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get dashboard analytics."""
    col = get_contacts_collection()

    # Basic counts
    total = col.count_documents({})
    if total == 0:
        return jsonify({
            'total_contacts': 0, 'unique_companies': 0,
            'unique_cities': 0, 'duplicate_count': 0,
            'quality_score': 0, 'email_types': {},
            'validation_statuses': {}, 'top_cities': [],
            'top_domains': [], 'all_cities': []
        })

    unique_companies = len(col.distinct('company'))

    # City distribution via aggregation
    city_pipeline = [
        {'$unwind': '$locations'},
        {'$group': {'_id': '$locations', 'count': {'$sum': 1}}},
        {'$sort': {'count': -1}}
    ]
    city_results = list(col.aggregate(city_pipeline))
    cities = {r['_id']: r['count'] for r in city_results}

    # Email type distribution
    email_type_pipeline = [
        {'$group': {'_id': {'$ifNull': ['$email_type', 'unknown']}, 'count': {'$sum': 1}}}
    ]
    email_types = {r['_id']: r['count'] for r in col.aggregate(email_type_pipeline)}

    # Validation status distribution
    val_pipeline = [
        {'$group': {
            '_id': {'$ifNull': ['$validation.status', 'pending']},
            'count': {'$sum': 1}
        }}
    ]
    val_statuses = {r['_id']: r['count'] for r in col.aggregate(val_pipeline)}

    # Domain distribution
    domain_pipeline = [
        {'$match': {'domain': {'$ne': ''}}},
        {'$group': {'_id': '$domain', 'count': {'$sum': 1}}},
        {'$sort': {'count': -1}},
        {'$limit': 20}
    ]
    top_domains = [[r['_id'], r['count']] for r in col.aggregate(domain_pipeline)]

    # Top cities
    top_cities = [[c, cnt] for c, cnt in sorted(cities.items(), key=lambda x: -x[1])[:20]]

    # Duplicate count
    dup_pipeline = [
        {'$group': {'_id': '$email', 'count': {'$sum': 1}}},
        {'$match': {'count': {'$gt': 1}}},
        {'$group': {'_id': None, 'total_dupes': {'$sum': {'$subtract': ['$count', 1]}}}}
    ]
    dup_result = list(col.aggregate(dup_pipeline))
    dupe_count = dup_result[0]['total_dupes'] if dup_result else 0

    # Data quality score (0-100)
    syntax_valid = col.count_documents({'validation.syntax': True})
    corporate = email_types.get('corporate', 0)
    non_empty = col.count_documents({
        'email': {'$ne': ''},
        'company': {'$ne': 'Unknown'}
    })

    quality_score = 0
    if total > 0:
        quality_score = round(
            (syntax_valid / total * 40) +
            (corporate / total * 30) +
            (non_empty / total * 20) +
            ((total - dupe_count) / total * 10)
        )

    # Unique cities list for filter dropdown
    all_cities = sorted(col.distinct('locations'))

    return jsonify({
        'total_contacts': total,
        'unique_companies': unique_companies,
        'unique_cities': len(cities),
        'duplicate_count': dupe_count,
        'quality_score': quality_score,
        'email_types': email_types,
        'validation_statuses': val_statuses,
        'top_cities': top_cities,
        'top_domains': top_domains,
        'all_cities': all_cities
    })


@app.route('/api/export', methods=['GET'])
def export_data():
    """Export contacts as CSV."""
    col = get_contacts_collection()
    records = list(col.find({}, {'_id': 0}))
    fmt = request.args.get('format', 'csv')

    if fmt == 'json':
        output = io.BytesIO()
        output.write(json.dumps(records, ensure_ascii=False, indent=2, default=str).encode('utf-8'))
        output.seek(0)
        return send_file(output, mimetype='application/json',
                         as_attachment=True,
                         download_name='hr_contacts_export.json')

    # CSV export
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Company', 'Location', 'Email', 'Domain',
                     'Email Type', 'Syntax Valid', 'MX Valid', 'SMTP Valid',
                     'Validation Status', 'Added At'])

    for r in records:
        val = r.get('validation', {})
        writer.writerow([
            r['id'], r['company'], r['location'], r['email'], r['domain'],
            r.get('email_type', ''), val.get('syntax', ''), val.get('mx', ''),
            val.get('smtp', ''), val.get('status', ''), r.get('added_at', '')
        ])

    output.seek(0)
    bytes_output = io.BytesIO(output.getvalue().encode('utf-8'))
    return send_file(bytes_output, mimetype='text/csv',
                     as_attachment=True,
                     download_name='hr_contacts_export.csv')


# ═══════════════════════════════════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    print("\n  Job Hunter - HR Data Command Center")
    print("  ------------------------------------")
    print("  Open http://localhost:5000 in your browser\n")
    app.run(debug=True, port=5000)

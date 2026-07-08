"""
Job Hunter — HR Data Command Center
Flask Backend API Server
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

app = Flask(__name__, static_folder='static', template_folder='templates')

DATA_FILE = 'data.json'
data_lock = Lock()

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
# DATA HELPERS
# ═══════════════════════════════════════════════════════════════════════

def load_data():
    """Load contacts from JSON file."""
    with data_lock:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    return []


def save_data(records):
    """Save contacts to JSON file."""
    with data_lock:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(records, f, ensure_ascii=False, indent=2)


def get_next_id(records):
    """Get the next available ID."""
    if not records:
        return 1
    return max(r['id'] for r in records) + 1


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
    records = load_data()

    # Search
    search = request.args.get('search', '').lower().strip()
    if search:
        records = [r for r in records if
                   search in r.get('company', '').lower() or
                   search in r.get('email', '').lower() or
                   search in r.get('location', '').lower()]

    # Filter by city
    city = request.args.get('city', '').strip()
    if city:
        records = [r for r in records if city.lower() in
                   [loc.lower() for loc in r.get('locations', [])]]

    # Filter by email type
    email_type = request.args.get('email_type', '').strip()
    if email_type:
        records = [r for r in records if r.get('email_type') == email_type]

    # Filter by validation status
    val_status = request.args.get('validation_status', '').strip()
    if val_status:
        records = [r for r in records if
                   r.get('validation', {}).get('status') == val_status]

    total = len(records)

    # Pagination
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))
    start = (page - 1) * per_page
    end = start + per_page
    paginated = records[start:end]

    return jsonify({
        'contacts': paginated,
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

    records = load_data()

    # Check for duplicate email
    if any(r['email'] == email for r in records):
        return jsonify({'error': f'Email {email} already exists'}), 409

    domain = email.split('@')[-1] if '@' in email else ''
    raw_locations = [loc.strip() for loc in location.replace(',', '/').split('/') if loc.strip()]
    if not raw_locations:
        raw_locations = ['Unknown']
    normalized = [normalize_city(loc) for loc in raw_locations]

    syntax_valid = is_valid_email_syntax(email)

    new_record = {
        'id': get_next_id(records),
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

    records.append(new_record)
    save_data(records)

    return jsonify({'message': 'Contact added', 'contact': new_record}), 201


@app.route('/api/contacts/<int:contact_id>', methods=['PUT'])
def update_contact(contact_id):
    """Update an existing contact."""
    data = request.get_json()
    records = load_data()

    contact = next((r for r in records if r['id'] == contact_id), None)
    if not contact:
        return jsonify({'error': 'Contact not found'}), 404

    if 'company' in data:
        contact['company'] = data['company'].strip()
    if 'location' in data:
        contact['location'] = data['location'].strip()
        raw_locs = [l.strip() for l in data['location'].replace(',', '/').split('/') if l.strip()]
        contact['locations'] = [normalize_city(l) for l in raw_locs] or ['Unknown']
    if 'email' in data:
        new_email = data['email'].strip().lower()
        # Check duplicate (excluding self)
        if any(r['email'] == new_email and r['id'] != contact_id for r in records):
            return jsonify({'error': f'Email {new_email} already exists'}), 409
        contact['email'] = new_email
        contact['domain'] = new_email.split('@')[-1] if '@' in new_email else ''
        contact['email_type'] = classify_email(contact['domain'])
        contact['validation'] = {
            'syntax': is_valid_email_syntax(new_email),
            'mx': None, 'smtp': None,
            'status': 'valid_syntax' if is_valid_email_syntax(new_email) else 'invalid_syntax'
        }

    save_data(records)
    return jsonify({'message': 'Contact updated', 'contact': contact})


@app.route('/api/contacts/<int:contact_id>', methods=['DELETE'])
def delete_contact(contact_id):
    """Delete a contact."""
    records = load_data()
    original_len = len(records)
    records = [r for r in records if r['id'] != contact_id]

    if len(records) == original_len:
        return jsonify({'error': 'Contact not found'}), 404

    save_data(records)
    return jsonify({'message': 'Contact deleted'})


@app.route('/api/contacts/bulk-delete', methods=['POST'])
def bulk_delete():
    """Delete multiple contacts by IDs."""
    data = request.get_json()
    ids_to_delete = set(data.get('ids', []))

    records = load_data()
    original_len = len(records)
    records = [r for r in records if r['id'] not in ids_to_delete]
    deleted = original_len - len(records)

    save_data(records)
    return jsonify({'message': f'{deleted} contacts deleted', 'deleted': deleted})


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

    # Update in data if this email exists
    records = load_data()
    for r in records:
        if r['email'] == email:
            r['validation'] = {
                'syntax': result['syntax'],
                'mx': result['mx'],
                'smtp': result['smtp'],
                'status': result['status']
            }
    save_data(records)

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
    records = load_data()

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
            record['validation'] = {
                'syntax': result['syntax'],
                'mx': result['mx'],
                'smtp': result['smtp'],
                'status': result['status']
            }
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

        # Save progress every 50 records
        if (i + 1) % 50 == 0:
            save_data(records)

    save_data(records)
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
    records = load_data()
    changes = []

    if operation == 'normalize_cities':
        for r in records:
            raw_locs = [l.strip() for l in r['location'].replace(',', '/').split('/') if l.strip()]
            new_locs = [normalize_city(l) for l in raw_locs]
            if new_locs != r.get('locations', []):
                changes.append({
                    'id': r['id'],
                    'field': 'locations',
                    'old': r.get('locations', []),
                    'new': new_locs
                })
                r['locations'] = new_locs
                r['is_cleaned'] = True

    elif operation == 'remove_invalid_emails':
        valid_records = []
        for r in records:
            if not is_valid_email_syntax(r['email']):
                changes.append({
                    'id': r['id'],
                    'action': 'removed',
                    'reason': 'invalid email syntax',
                    'email': r['email']
                })
            else:
                valid_records.append(r)
        records = valid_records

    elif operation == 'flag_personal_emails':
        for r in records:
            old_type = r.get('email_type', '')
            new_type = classify_email(r.get('domain', ''))
            if old_type != new_type:
                changes.append({
                    'id': r['id'],
                    'field': 'email_type',
                    'old': old_type,
                    'new': new_type
                })
            r['email_type'] = new_type

    elif operation == 'trim_whitespace':
        for r in records:
            old_company = r['company']
            new_company = ' '.join(r['company'].split())  # Normalize whitespace
            if old_company != new_company:
                changes.append({
                    'id': r['id'],
                    'field': 'company',
                    'old': old_company,
                    'new': new_company
                })
                r['company'] = new_company
                r['is_cleaned'] = True

    elif operation == 'fix_casing':
        for r in records:
            old_company = r['company']
            # Title case but preserve common abbreviations
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
                r['company'] = new_company
                r['is_cleaned'] = True

    elif operation == 'remove_empty_entries':
        valid_records = []
        for r in records:
            if not r['email'] or not r['company'] or r['company'] == 'Unknown':
                changes.append({
                    'id': r['id'],
                    'action': 'removed',
                    'reason': 'empty company or email',
                    'company': r['company'],
                    'email': r['email']
                })
            else:
                valid_records.append(r)
        records = valid_records

    else:
        return jsonify({'error': f'Unknown operation: {operation}'}), 400

    save_data(records)
    return jsonify({
        'message': f'Cleaning operation "{operation}" completed',
        'changes_count': len(changes),
        'changes': changes[:100],  # Return first 100 changes for preview
        'total_records': len(records)
    })


@app.route('/api/dedup', methods=['POST'])
def deduplicate():
    """Find and remove duplicate entries based on email."""
    data = request.get_json()
    preview_only = data.get('preview', True)

    records = load_data()
    seen_emails = {}
    duplicates = []
    unique_records = []

    for r in records:
        email = r['email'].lower().strip()
        if email in seen_emails:
            duplicates.append({
                'duplicate': r,
                'original_id': seen_emails[email]
            })
        else:
            seen_emails[email] = r['id']
            unique_records.append(r)

    if not preview_only:
        save_data(unique_records)

    return jsonify({
        'message': 'Deduplication ' + ('preview' if preview_only else 'applied'),
        'duplicates_found': len(duplicates),
        'duplicates': duplicates[:100],  # First 100 for preview
        'records_after': len(unique_records),
        'applied': not preview_only
    })


# ═══════════════════════════════════════════════════════════════════════
# API — Stats & Export
# ═══════════════════════════════════════════════════════════════════════

@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get dashboard analytics."""
    records = load_data()

    # Basic counts
    total = len(records)
    unique_companies = len(set(r['company'] for r in records))

    # City distribution
    cities = {}
    for r in records:
        for loc in r.get('locations', ['Unknown']):
            cities[loc] = cities.get(loc, 0) + 1

    # Email type distribution
    email_types = {}
    for r in records:
        t = r.get('email_type', 'unknown')
        email_types[t] = email_types.get(t, 0) + 1

    # Validation status distribution
    val_statuses = {}
    for r in records:
        s = r.get('validation', {}).get('status', 'pending')
        val_statuses[s] = val_statuses.get(s, 0) + 1

    # Domain distribution
    domains = {}
    for r in records:
        d = r.get('domain', '')
        if d:
            domains[d] = domains.get(d, 0) + 1

    # Top cities (sorted by count)
    top_cities = sorted(cities.items(), key=lambda x: -x[1])[:20]

    # Top domains
    top_domains = sorted(domains.items(), key=lambda x: -x[1])[:20]

    # Duplicate count
    emails_seen = set()
    dupe_count = 0
    for r in records:
        if r['email'] in emails_seen:
            dupe_count += 1
        else:
            emails_seen.add(r['email'])

    # Data quality score (0-100)
    syntax_valid = sum(1 for r in records if r.get('validation', {}).get('syntax'))
    corporate = email_types.get('corporate', 0)
    non_empty = sum(1 for r in records if r['email'] and r['company'] != 'Unknown')

    quality_score = 0
    if total > 0:
        quality_score = round(
            (syntax_valid / total * 40) +
            (corporate / total * 30) +
            (non_empty / total * 20) +
            ((total - dupe_count) / total * 10)
        )

    # Unique cities list for filter dropdown
    all_cities = sorted(set(
        loc for r in records for loc in r.get('locations', [])
    ))

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
    records = load_data()
    fmt = request.args.get('format', 'csv')

    if fmt == 'json':
        output = io.BytesIO()
        output.write(json.dumps(records, ensure_ascii=False, indent=2).encode('utf-8'))
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

#!/usr/bin/env python
"""
Adds indexes on foreign-key columns that lacked one — Postgres never indexes
a FK automatically, only the primary key. These columns are filtered on
constantly (vehicle/license detail pages, officer history, SmartTech reports,
insurance dashboard, phone usage history) and most of the tables they belong
to (fines, vehicle_history, point_reduction_history, photo_submissions, ...)
grow without bound as the app is used, unlike Vehicle/DriverLicense which
stay roughly capped by fleet/license count.

Purely additive and reversible: CREATE INDEX never reads/writes row data, it
only builds a lookup structure alongside the table. Safe to run against a
live database.

On Postgres it uses CREATE INDEX CONCURRENTLY so it never blocks reads or
writes on the table while building (each statement runs in its own implicit
transaction, since CONCURRENTLY cannot run inside one). On SQLite (local
dev), CONCURRENTLY isn't supported, so a plain CREATE INDEX is used instead —
harmless locally since dev tables are tiny.

Idempotent: IF NOT EXISTS means it's safe to re-run.

Usage:
    python add_vehicle_fk_indexes.py            # against local SQLite (police.db)
    DATABASE_URL=postgresql://... python add_vehicle_fk_indexes.py   # against Render Postgres
"""
from app import create_app, db

INDEXES = [
    ('ix_fines_vehicle_id', 'fines', ['vehicle_id']),
    ('ix_vehicle_history_vehicle_id', 'vehicle_history', ['vehicle_id']),
    ('ix_vehicle_edit_requests_vehicle_id', 'vehicle_edit_requests', ['vehicle_id']),
    ('ix_technical_inspections_vehicle_id', 'technical_inspections', ['vehicle_id']),
    ('ix_vehicle_warnings_vehicle_id', 'vehicle_warnings', ['vehicle_id']),
    ('ix_technical_inspection_appointments_vehicle_id', 'technical_inspection_appointments', ['vehicle_id']),
    ('ix_qr_code_payments_vehicle_id', 'qr_code_payments', ['vehicle_id']),
    ('ix_vehicle_insurance_assignments_vehicle_id', 'vehicle_insurance_assignments', ['vehicle_id']),
    ('ix_vehicle_insurance_assignments_insurance_account_id', 'vehicle_insurance_assignments', ['insurance_account_id']),
    ('ix_photo_submissions_vehicle_id', 'photo_submissions', ['vehicle_id']),
    ('ix_vehicle_transfers_vehicle_id', 'vehicle_transfers', ['vehicle_id']),
    # licenses
    ('ix_license_edit_requests_license_id', 'license_edit_requests', ['license_id']),
    ('ix_license_print_requests_license_id', 'license_print_requests', ['license_id']),
    ('ix_point_reduction_history_license_id', 'point_reduction_history', ['license_id']),
    ('ix_license_dossiers_license_id', 'license_dossiers', ['license_id']),
    # phone usage ("Historique d'Utilisation")
    ('ix_phone_usages_phone_id', 'phone_usages', ['phone_id']),
    ('ix_phone_usages_user_id', 'phone_usages', ['user_id']),
    # other growing/hot FK lookups found in the same audit
    ('ix_user_history_user_id', 'user_history', ['user_id']),
    ('ix_technical_inspection_appointments_payment_id', 'technical_inspection_appointments', ['payment_id']),
    ('ix_insurance_accounts_insurance_id', 'insurance_accounts', ['insurance_id']),
    ('ix_photo_submissions_user_id', 'photo_submissions', ['user_id']),
    ('ix_photo_submissions_reviewed_by', 'photo_submissions', ['reviewed_by']),
    ('ix_vehicle_transfers_processed_by', 'vehicle_transfers', ['processed_by']),
    ('ix_st_stock_sales_stock_item_id', 'st_stock_sales', ['stock_item_id']),
]


def main():
    app = create_app()
    with app.app_context():
        is_postgres = db.engine.url.get_backend_name() == 'postgresql'
        # AUTOCOMMIT: each statement runs on its own, outside any transaction
        # block — required by Postgres for CREATE INDEX CONCURRENTLY.
        with db.engine.connect().execution_options(isolation_level='AUTOCOMMIT') as conn:
            for name, table, cols in INDEXES:
                col_list = ', '.join(cols)
                concurrently = 'CONCURRENTLY ' if is_postgres else ''
                sql = f'CREATE INDEX {concurrently}IF NOT EXISTS {name} ON {table} ({col_list})'
                conn.execute(db.text(sql))
                print(f'✓ {name} on {table}({col_list})')
        print('Done.')


if __name__ == '__main__':
    main()

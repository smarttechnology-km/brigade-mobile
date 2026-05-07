#!/usr/bin/env python
import sqlite3
import os

db_path = '/Users/mohamedabdallah/Desktop/Police/police.db'

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    # Check current schema
    print("Checking current schema...")
    cursor.execute("PRAGMA table_info(penalty_rates);")
    columns = cursor.fetchall()
    print("Current columns:")
    for col in columns:
        print(f"  {col}")
    
    # Check if penalty_per_day already exists
    has_penalty_per_day = any(col[1] == 'penalty_per_day' for col in columns)
    has_penalty_kmf = any(col[1] == 'penalty_kmf' for col in columns)
    
    if has_penalty_per_day and not has_penalty_kmf:
        print("✓ Column penalty_per_day already exists, no migration needed")
    elif has_penalty_kmf and not has_penalty_per_day:
        print("Migrating penalty_kmf to penalty_per_day...")
        
        # Rename column (SQLite doesn't support ALTER COLUMN, so we use the rename table approach)
        cursor.execute("BEGIN TRANSACTION;")
        
        # Create backup
        cursor.execute("ALTER TABLE penalty_rates RENAME TO penalty_rates_old;")
        
        # Create new table with correct schema
        cursor.execute("""
            CREATE TABLE penalty_rates (
                id INTEGER PRIMARY KEY,
                days_late_min INTEGER NOT NULL,
                days_late_max INTEGER NOT NULL,
                penalty_per_day NUMERIC(10, 2) NOT NULL,
                description VARCHAR(255),
                is_active BOOLEAN NOT NULL DEFAULT 1,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                UNIQUE(days_late_min, days_late_max)
            );
        """)
        
        # Copy data from old table
        cursor.execute("""
            INSERT INTO penalty_rates (id, days_late_min, days_late_max, penalty_per_day, description, is_active, created_at, updated_at)
            SELECT id, days_late_min, days_late_max, penalty_kmf, description, is_active, created_at, updated_at FROM penalty_rates_old;
        """)
        
        # Drop old table
        cursor.execute("DROP TABLE penalty_rates_old;")
        
        cursor.execute("COMMIT;")
        
        print("✓ Migration completed successfully")
        
        # Verify
        cursor.execute("PRAGMA table_info(penalty_rates);")
        columns = cursor.fetchall()
        print("New columns:")
        for col in columns:
            print(f"  {col}")
    else:
        print("⚠ Unexpected schema state!")
        
except Exception as e:
    print(f"Error: {str(e)}")
    conn.rollback()
finally:
    conn.close()

import sqlite3

def migrate():
    conn = sqlite3.connect("instance/agroo.db")
    cursor = conn.cursor()
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN pin_hash VARCHAR(255);")
        print("Successfully added pin_hash column to users table.")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            print("pin_hash column already exists.")
        else:
            print(f"Error adding pin_hash: {e}")
            
    # For making phone_number nullable in SQLite, it's complex (requires recreating table).
    # Since Ghost Auth users don't have a phone number, we will insert a dummy phone number 
    # at the application level if SQLite enforces the constraint, or we can just leave it as is
    # and handle it in the router.
    
    conn.commit()
    conn.close()

if __name__ == "__main__":
    migrate()

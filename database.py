import sqlite3
from datetime import datetime

class Database:
    def __init__(self):
        self.conn = sqlite3.connect('anon_bot.db', check_same_thread=False)
        self.create_tables()
    
    def create_tables(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS dialogs (
                dialog_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE,
                user_tag TEXT DEFAULT NULL,
                created_at TIMESTAMP,
                last_activity TIMESTAMP,
                is_active BOOLEAN DEFAULT 1
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                dialog_id INTEGER,
                from_admin BOOLEAN,
                text TEXT,
                media_id TEXT,
                media_type TEXT,
                sent_at TIMESTAMP,
                FOREIGN KEY (dialog_id) REFERENCES dialogs (dialog_id)
            )
        ''')
        self.conn.commit()
    
    def get_or_create_dialog(self, user_id, user_tag=None):
        cursor = self.conn.cursor()
        cursor.execute('SELECT dialog_id FROM dialogs WHERE user_id = ?', (user_id,))
        dialog = cursor.fetchone()
        
        if dialog:
            dialog_id = dialog[0]
            cursor.execute('''UPDATE dialogs 
                              SET last_activity = ?, user_tag = COALESCE(?, user_tag) 
                              WHERE dialog_id = ?''', 
                           (datetime.now(), user_tag, dialog_id))
            self.conn.commit()
            return dialog_id
        else:
            cursor.execute('''INSERT INTO dialogs 
                              (user_id, user_tag, created_at, last_activity) 
                              VALUES (?, ?, ?, ?)''', 
                           (user_id, user_tag, datetime.now(), datetime.now()))
            self.conn.commit()
            return cursor.lastrowid
    
    def get_all_active_dialogs(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT dialog_id, user_id, user_tag, last_activity 
            FROM dialogs 
            WHERE is_active = 1 
            ORDER BY last_activity DESC
        ''')
        return cursor.fetchall()
    
    def get_dialog_messages(self, dialog_id, limit=50):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT from_admin, text, media_type, sent_at 
            FROM messages 
            WHERE dialog_id = ? 
            ORDER BY sent_at ASC 
            LIMIT ?
        ''', (dialog_id, limit))
        return cursor.fetchall()
    
    def save_message(self, dialog_id, from_admin, text, media_id=None, media_type=None):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO messages (dialog_id, from_admin, text, media_id, media_type, sent_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (dialog_id, from_admin, text, media_id, media_type, datetime.now()))
        self.conn.commit()
        return cursor.lastrowid

db = Database()
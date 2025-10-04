import sqlite3
from datetime import datetime
import threading

class Database:
    def __init__(self, db_file='transcripts.db'):
        self.db_file = db_file
        self.local = threading.local()
        self.create_tables()
    
    def get_connection(self):
        """Get or create a connection for the current thread"""
        if not hasattr(self.local, 'connection'):
            self.local.connection = sqlite3.connect(self.db_file, check_same_thread=False)
            self.local.cursor = self.local.connection.cursor()
        return self.local.connection, self.local.cursor
    
    def create_tables(self):

        
        conn, cursor = self.get_connection()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transcripts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                text TEXT,
                summary TEXT,
                date TEXT NOT NULL
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS participants (
                transcript_id INTEGER,
                discord_user_id TEXT,
                FOREIGN KEY (transcript_id) REFERENCES transcripts(id)
            )
        ''')
        conn.commit()
    
    def save_transcript(self, name, text, summary, participant_ids):
        conn, cursor = self.get_connection()
        date = datetime.now().isoformat()
        cursor.execute(
            'INSERT INTO transcripts (name, text, summary, date) VALUES (?, ?, ?, ?)',
            (name, text, summary, date)
        )
        transcript_id = cursor.lastrowid
        
        for user_id in participant_ids:
            cursor.execute(
                'INSERT INTO participants (transcript_id, discord_user_id) VALUES (?, ?)',
                (transcript_id, str(user_id))
            )
        
        conn.commit()
        return transcript_id
    
    def search_transcripts(self, search_term):
        conn, cursor = self.get_connection()
        cursor.execute(
            'SELECT id, name, date FROM transcripts WHERE name LIKE ?',
            (f'%{search_term}%',)
        )
        return cursor.fetchall()
    
    def get_transcript(self, transcript_id):
        conn, cursor = self.get_connection()
        cursor.execute(
            'SELECT name, text, summary, date FROM transcripts WHERE id = ?',
            (transcript_id,)
        )
        return cursor.fetchone()

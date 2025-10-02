import sqlite3
from datetime import datetime

class Database:
    def __init__(self, db_file='transcripts.db'):
        self.connection = sqlite3.connect(db_file)
        self.cursor = self.connection.cursor()
        self.create_tables()
    
    def create_tables(self):
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS transcripts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                text TEXT,
                summary TEXT,
                date TEXT NOT NULL
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS participants (
                transcript_id INTEGER,
                discord_user_id TEXT,
                FOREIGN KEY (transcript_id) REFERENCES transcripts(id)
            )
        ''')
        self.connection.commit()
    
    def save_transcript(self, name, text, summary, participant_ids):
        date = datetime.now().isoformat()
        self.cursor.execute(
            'INSERT INTO transcripts (name, text, summary, date) VALUES (?, ?, ?, ?)',
            (name, text, summary, date)
        )
        transcript_id = self.cursor.lastrowid
        
        for user_id in participant_ids:
            self.cursor.execute(
                'INSERT INTO participants (transcript_id, discord_user_id) VALUES (?, ?)',
                (transcript_id, str(user_id))
            )
        
        self.connection.commit()
        return transcript_id
    
    def search_transcripts(self, search_term):
        self.cursor.execute(
            'SELECT id, name, date FROM transcripts WHERE name LIKE ?',
            (f'%{search_term}%',)
        )
        return self.cursor.fetchall()
    
    def get_transcript(self, transcript_id):
        self.cursor.execute(
            'SELECT name, text, summary, date FROM transcripts WHERE id = ?',
            (transcript_id,)
        )
        return self.cursor.fetchone()

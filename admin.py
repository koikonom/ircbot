import re
import time
import sqlite3

conn = sqlite3.connect('/Users/kyriakos/PycharmProjects/ircbot/ircbot.sqlite3')
curs = conn.cursor()
curs.execute('''CREATE TABLE  IF NOT EXISTS QUOTES (ID INTEGER PRIMARY KEY,
                                                    NICK TEXT,
                                                    QUOTE TEXT collate nocase,
                                                    QUOTE_DT NUMERIC,
                                                    ADDED_BY TEXT,
                                                    CHANNEL TEXT
                                                    )''')

with open('/Users/kyriakos/PycharmProjects/ircbot/quotes.txt', 'r') as f:
        for line in f:
            nick_match = re.match(r'\S*\s*<(\S*)>.*', line)
            if nick_match:
                nick = nick_match.groups()[0]
            else:
                nick = ''
            quote = line.strip()
            quote_dt = int(time.time())
            inserted_by = 'import_tool'
            channel = '#other'
            x = curs.execute(''' INSERT INTO QUOTES (NICK, QUOTE, QUOTE_DT, ADDED_BY, CHANNEL) VALUES (?, ?, ?, ?, ?)''',
                            (nick, quote, quote_dt, inserted_by, channel))
print time.time()
conn.commit()
print time.time()

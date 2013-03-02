from datetime import datetime, timedelta
import inspect
import random
import os
import re
import sys
import time
import urlparse

from lxml.html import fromstring
from twisted.enterprise.adbapi import ConnectionPool
from twisted.internet import protocol
from twisted.internet import defer, reactor
from twisted.web.client import Agent
from twisted.web.client import getPage
from twisted.words.protocols import irc

store_dir = './files/'
db_file = '/Users/kyriakos/PycharmProjects/ircbot/ircbot.sqlite3'

class IrcBot(irc.IRCClient):

    def __init__(self, *args, **kwargs):
        self.init_db()
        self.plugins = {'privmsg': [self.url_plugin, self.cmd_plugin],
                        'signedOn': [self.signon_plugin],
                        'joined': [self.joined_plugin]}

    @defer.inlineCallbacks
    def init_db(self):
        self.db = ConnectionPool('sqlite3', db_file)
        yield self.db.runQuery('''CREATE TABLE IF NOT EXISTS QUOTES (ID INTEGER PRIMARY KEY,
                                                    NICK TEXT,
                                                    QUOTE TEXT collate nocase,
                                                    QUOTE_DT NUMERIC,
                                                    ADDED_BY TEXT,
                                                    CHANNEL TEXT
                                                    )''')
        yield self.db.runQuery('''CREATE TABLE IF NOT EXISTS URLS (ID INTEGER PRIMARY KEY,
                                                    URL TEXT collate nocase,
                                                    URL_DT NUMERIC,
                                                    ADDED_BY TEXT,
                                                    CHANNEL TEXT
                                                    )''')

    ###############################################################################
    # Misc methods
    #############################################################################

    # Return the name of the method that calls funcname() as a string
    def funcname(self):
        return inspect.stack()[1][3]

    # Helper method that converts seconds to a string
    # in the format of "X days, X hours, X minutes, X seconds
    def get_time(self, sec):
        sec = timedelta(seconds=int(time.time()) - sec)
        dt = datetime(1, 1, 1) + sec
        msg = "%s seconds" % dt.second
        if dt.minute:
            msg = "%s minute(s)," % dt.minute + msg
        if dt.hour:
            msg = "%s hour(s)," % dt.hour + msg
        if dt.day - 1:
            msg = "%s day(s)," % (dt.day - 1) + msg
        return msg

    #############################################################################
    # Plugin code, to be moved to a separate file
    #############################################################################

    def signon_plugin(self):
        self.join(self.factory.channel)
        print "Signed on as %s." % (self.nickname,)

    def joined_plugin(self, channel):
        print "Joined %s." % (channel,)
        self.say(channel, 'hi')

    def cmd_plugin(self, user, channel, msg):
        cmd_dict = {'quote':self.quote,
                    'add':self.add_quote}

        if msg[0] == '!':
            cmd = msg.split()[0][1:]
            cmd_dict[cmd](user, channel, msg)

    def url_plugin(self, user, channel, msg):
        #Do not process commands
        if msg[0] == '!':
            return
        for tok in msg.split(' '):
            if urlparse.urlparse(tok).scheme[:4] == 'http':
                user = user.split('!')[0]
                self.store(tok, channel, user)

    @defer.inlineCallbacks
    def quote(self, user, channel, msg):
        toks = msg.split(' ')
        if len(toks) < 2:
            query = '''SELECT id, quote FROM quotes ORDER BY RANDOM() LIMIT 1'''
            quotes = yield self.db.runQuery(query,)
        else:
            query = '''SELECT id, quote from quotes where quote like ?'''
            pattern = '%%%s%%' % ' '.join(toks[1:])
            quotes = yield self.db.runQuery(query, (pattern,))

        if len(quotes):
            if len(quotes) > 1:
                quotes = [random.choice(quotes)]
            msg = '[%s] %s' % (str(quotes[0][0]), str(quotes[0][1]))
            self.say(channel, msg)

    @defer.inlineCallbacks
    def add_quote(self, user, channel, msg):
        print user,channel,msg
        quote = ' '.join(msg.split(' ')[1:])
        nick_match = re.match(r'\S*\s*<(\S*)>.*', quote)
        if nick_match:
            nick = nick_match.groups()[0]
        else:
            nick = ''
        user = user.split('!')[0]
        query = '''INSERT INTO quotes (NICK, QUOTE, QUOTE_DT, ADDED_BY, CHANNEL) VALUES (?, ?, ?, ?, ?)'''
        quotes = yield self.db.runQuery(query, (nick, quote, int(time.time()), user, channel))
        self.say(channel, 'Quote added!')

    @defer.inlineCallbacks
    def store(self, url, channel, nick):
        # find existing url
        query = '''SELECT * FROM urls WHERE url = ?'''
        result = yield self.db.runQuery(query, (url,))
        if not result:
            dt = int(time.time())
            query = '''INSERT INTO urls (URL, URL_DT, ADDED_BY, CHANNEL) VALUES (?, ?, ?, ?)'''
            quotes = yield self.db.runQuery(query, (url, dt, nick, channel))
            self.process_url(url, channel, dt)
        else:
            res = result[0]
            src_nick = res[3]
            src_channel = res[4]
            ts = self.get_time(int(res[2]))
            msg = "OLD! %s mentioned it %s ago" % (src_nick, ts)
            if src_channel != channel:
                msg += ", in %s" % src_channel
            self.say(channel, str(msg))

    # Check if the url is an html page or a image.
    # If it's HTML extract the title, otherwise store the image
    # in the DB.
    @defer.inlineCallbacks
    def process_url(self, url, channel, dt):
        agent = Agent(reactor)
        resp = yield agent.request('HEAD', url)
        type = resp.headers.getRawHeaders('Content-Type', default='')
        if type[0][:9] == 'text/html':
            html = yield getPage(url)
            title = fromstring(html).xpath('/html/head/title')[0].text
            msg = "[ %s ]" % title
            self.say(channel, str(msg))
        elif type[0].split('/')[0] == 'image':
            self.store_image(url, dt)
        else:
            self.say(channel, 'unknown mime type: %s' % str(type))

    @defer.inlineCallbacks
    def store_image(self, url, dt):
        #save the file.
        img_data = yield getPage(url)
        filename = urlparse.urlparse(url).path.split('/')[-1]
        new_path = os.path.join(store_dir, filename[0], ''.join([str(y) for y in filename[0:2]]))
        if not os.path.exists(new_path):
            yield os.makedirs(new_path)
        tgt_filename = os.path.join(new_path, '%s_%s' %(dt, filename))
        f = yield open(tgt_filename, 'wb')
        try:
            yield f.write(img_data)
            self.say(channel, 'image stored')
        except Exception, e:
            self.day(channel, 'failed to store image: %s' % e.message)
        finally:
            yield f.close()

    ###############################################################################
    #   IRC Handlers. Each handler gets a list of plugins and evaluates them      #
    ###############################################################################
    def signedOn(self):
        for p in self.plugins[self.funcname()]:
            p()

    def joined(self, channel):
        for p in self.plugins[self.funcname()]:
            p(channel)

    def privmsg(self, user, channel, msg):
        for p in self.plugins[self.funcname()]:
            p(user, channel, msg)


class IrcBotFactory(protocol.ClientFactory):
    protocol = IrcBot

    def __init__(self, channel, nickname='kyrtest__'):
        self.channel = channel
        self.nickname = nickname

    def clientConnectionLost(self, connector, reason):
        print "Lost connection (%s), reconnecting." % (reason,)
        connector.connect()

    def clientConnectionFailed(self, connector, reason):
        print "Could not connect: %s" % (reason,)


def usage():
    print "Usage: %s <server> <channel> <nick>" % sys.argv[0]

if __name__ == "__main__":
    if len(sys.argv) < 4:
        usage()
        sys.exit(1)
    server = sys.argv[1]
    channel = sys.argv[2]
    nick = sys.argv[3]
    irc_factory = IrcBotFactory('#' + channel, nick)
    reactor.connectTCP(server, 6667, irc_factory)
    reactor.run()

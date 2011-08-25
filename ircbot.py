import sys
import time
import urlparse
import inspect

from datetime import datetime, timedelta

import txmongo

from twisted.internet import reactor
from twisted.words.protocols import irc
from twisted.internet import protocol
from twisted.internet import defer, reactor
from twisted.web.client import Agent
from twisted.web.client import getPage
from lxml.html import fromstring

class IrcBot(irc.IRCClient):

    def __init__(self, *args, **kwargs):
        self.init_db()
        self.plugins = {'privmsg': [self.url_plugin],
                        'signedOn': [self.signon_plugin],
                        'joined': [self.joined_plugin]}

#############################################################################
# Misc methods
#############################################################################

    # Return the name of the method that calls funcname() as a string
    def funcname(self):
        return inspect.stack()[1][3]

    # Helper method that converts seconds to a string 
    # in the format of "X days, X hours, X minutes, X seconds
    def get_time(self, sec):
        sec = timedelta(seconds=int(time.time()) - sec)
        d = datetime(1,1,1) + sec
        msg = "%s seconds" % d.second
        if d.minute: msg = "%s minute(s)," % d.minute + msg
        if d.hour: msg = "%s hour(s)," % d.hour + msg
        if d.day-1: msg = "%s day(s)," % (d.day-1) + msg
        return msg

    # Connect to mongoDB
    @defer.inlineCallbacks
    def init_db(self):
        self.mongo_conn = yield txmongo.MongoConnection()

#############################################################################
# Plugin code, to be moved to a separate file
#############################################################################

    def signon_plugin(self):
        print "signon_plugin"
        self.join(self.factory.channel)
        print "Signed on as %s." % (self.nickname,)

    def joined_plugin(self, channel):
        print "Joined %s." % (channel,)
        self.say(channel, 'hi')

    def url_plugin(self, user, channel, msg):
        for tok in msg.split(' '):
            if urlparse.urlparse(tok).scheme[:4] == 'http':
                user = user.split('!')[0]
                self.store(tok, channel, user)

    @defer.inlineCallbacks
    def store(self, url, chan, nick):
        mongo = self.mongo_conn
        foo = mongo.ircbot # database
        test = foo.urls    # collection

        result = yield test.find({'url':url})
        if not result:
            self.process_url(url, chan)
            result = yield test.insert({'url':url, 'chan':chan, 'nick':nick, 
                                    'ts':int(time.time())}, safe=True)
        else:
            res = result[0]
            src_nick = res['nick']
            src_chan = res['chan']
            ts = res['ts']
            msg = "OLD! %s mentioned it %s ago" % (src_nick, self.get_time(int(ts)))
            if src_chan != chan: msg = msg + ", in %s" % src_chan
            self.say(chan, str(msg))

    # Check if the url is an html page or a image.
    # If it's HTML extract the title, otherwise store the image
    # in the DB.
    @defer.inlineCallbacks
    def process_url(self, url, chan):
        agent = Agent(reactor)
        resp = yield agent.request('HEAD', url)
        type = resp.headers.getRawHeaders('Content-Type', default='')
        if type[0][:9] == 'text/html':
            html = yield getPage(url)
            title = fromstring(html).xpath('/html/head/title')[0].text
            msg = "[ %s ]" % title
            self.say(chan, str(msg))
        elif type[0].split('/') == 'image':
            self.say(chan, "Image Stored")


    def _get_nickname(self):
        return self.factory.nickname
    nickname = property(_get_nickname)

###############################################################################
#   IRC Handlers. Each handler gets a list of plugins and evaluates them      #
###############################################################################
    def signedOn(self):
        for p in self.plugins[self.funcname()]: p()

    def joined(self, channel):
        for p in self.plugins[self.funcname()]: p(channel)

    def privmsg(self, user, channel, msg):
        for p in self.plugins[self.funcname()]: p(user, channel, msg)

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
    chan = sys.argv[1]
    reactor.connectTCP(sys.argv[1], 6667, IrcBotFactory('#' + sys.argv[2], sys.argv[3]))
    reactor.run()

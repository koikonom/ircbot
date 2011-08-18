import sys
import time
import urlparse

import txmongo
from twisted.internet import reactor
from twisted.words.protocols import irc
from twisted.internet import protocol
from twisted.internet import defer, reactor

class IrcBot(irc.IRCClient):

    @defer.inlineCallbacks
    def store(self, url, chan, nick):
        mongo = self.mongo_conn
        foo = mongo.ircbot # database
        test = foo.urls    # collection

        result = yield test.find({'url':url})
        if not result:
            result = yield test.insert({'url':url, 'chan':chan, 'nick':nick, 
                                    'ts':int(time.time())}, safe=True)
            self.say(chan, "Stored")
        else:
            res = result[0]
            src_nick = res['nick']
            src_chan = res['chan']
            ts = res['ts']
            msg = "OLD! %s mentioned it %s ago" % (src_nick, ts)
            if src_chan != chan: msg = msg + ", in %s" % src_chan
            self.say(chan, str(msg))

    def _get_nickname(self):
        return self.factory.nickname
    nickname = property(_get_nickname)

    @defer.inlineCallbacks
    def signedOn(self):
        self.mongo_conn = yield txmongo.MongoConnection()
        self.join(self.factory.channel)
        print "Signed on as %s." % (self.nickname,)

    def joined(self, channel):
        print "Joined %s." % (channel,)

    def privmsg(self, user, channel, msg):
        for tok in msg.split(' '):
            if urlparse.urlparse(tok).scheme[:4] == 'http':
                self.store(tok, chan, user)
        print user, channel, msg

    def modeChanged(self, user, channel, set, modes, args):
        print user, channel, set, modes, args

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


if __name__ == "__main__":
    chan = sys.argv[1]
    reactor.connectTCP('irc.freenode.net', 6667, IrcBotFactory('#' + chan))
    reactor.run()

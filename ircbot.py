import inspect
from datetime import datetime, timedelta
import sys
import time
import urlparse

from lxml.html import fromstring
from twisted.words.protocols import irc
from twisted.internet import protocol
from twisted.internet import defer, reactor
from twisted.web.client import Agent
from twisted.web.client import getPage
import txmongo
from txmongo.gridfs import GridFS

MAX_SIZE = 1048576
FS_COLLECTION = 'fs'


class IrcBot(irc.IRCClient):

    def __init__(self, *args, **kwargs):
        self.init_db()
        self.plugins = {'privmsg': [self.url_plugin, self.cmd_plugin],
                        'signedOn': [self.signon_plugin],
                        'joined': [self.joined_plugin]}

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

    # Connect to mongoDB
    @defer.inlineCallbacks
    def init_db(self):
        self.mongo_conn = yield txmongo.MongoConnection()
        self.url_collection = self.mongo_conn.ircbot.urls
        self.file_collection = self.mongo_conn.ircbot.fs

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

    def cmd_plugin(self, user, channel, msg):
        cmd_dict = {'list':self.list,
                    'get':self.get}
        if msg[0] == '!':
            cmd = msg.split()[0][1:]
            self.say(channel, 'executing command: %s' % cmd)
            cmd_dict[cmd](user, channel, msg)
        
    @defer.inlineCallbacks       
    def list(self, user, channel, msg):
        gfs = GridFS(self.mongo_conn.ircbot, FS_COLLECTION)
        files = yield gfs.list()
        self.say(channel, 'files found: %s' % str(files))

    @defer.inlineCallbacks       
    def get(self, user, channel, msg):
        toks = msg.split()
        if len(toks) < 2:
            self.say(channel, 'file missing')
        filename = toks[1]
        gfs = GridFS(self.mongo_conn.ircbot, FS_COLLECTION)
        file_ver = yield gfs.get_last_version(filename)  
        self.say(channel, 'file found: %s' % str(file_ver.md5))

    def url_plugin(self, user, channel, msg):
        #Do not process commands
        if msg[0] == '!':
            return
        for tok in msg.split(' '):
            if urlparse.urlparse(tok).scheme[:4] == 'http':
                user = user.split('!')[0]
                self.store(tok, channel, user)

    @defer.inlineCallbacks
    def store(self, url, channel, nick):
        result = yield self.url_collection.find({'url': url})
        if not result:
            result = yield self.url_collection.insert({'url': url, 'chan': channel, 'nick': nick,
                                                'ts': int(time.time())}, safe=True)
            self.process_url(url, channel)
        else:
            res = result[0]
            src_nick = res['nick']
            src_channel = res['chan']
            ts = self.get_time(int(res['ts']))
            msg = "OLD! %s mentioned it %s ago" % (src_nick, ts)
            if src_channel != channel:
                msg = msg + ", in %s" % src_channel
            self.say(channel, str(msg))

    # Check if the url is an html page or a image.
    # If it's HTML extract the title, otherwise store the image
    # in the DB.
    @defer.inlineCallbacks
    def process_url(self, url, channel):
        agent = Agent(reactor)
        resp = yield agent.request('HEAD', url)
        type = resp.headers.getRawHeaders('Content-Type', default='')
        if type[0][:9] == 'text/html':
            html = yield getPage(url)
            title = fromstring(html).xpath('/html/head/title')[0].text
            msg = "[ %s ]" % title
            self.say(channel, str(msg))
        elif type[0].split('/')[0] == 'image':
            self.store_image(url, type[0])
        else:
            self.say(channel, 'unknown mime type: %s' % str(type))

    @defer.inlineCallbacks
    def store_image(self, url, type):
        self.say(channel, 'storing image from %s' % url)

        #save the file.
        img_data = yield getPage(url)
        gfs = GridFS(self.mongo_conn.ircbot, FS_COLLECTION)
        filename = urlparse.urlparse(url).path.split('/')[-1]
        ifp = gfs.new_file(filename=filename, content_type=type)
        yield ifp.write(img_data)
        yield ifp.close()

        #link it to the URL in the DB.
        url_doc = yield self.url_collection.find_one({'url':url})
        url_doc['file'] = ifp._id
        yield self.url_collection.save(url_doc)
        
    def _get_nickname(self):
        return self.factory.nickname
    nickname = property(_get_nickname)

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

#!/usr/bin/env python
#
# Chinese IRC botttt.
#
# Author: Yacin Nadji <yacin@gatech.edu>
#

import sys
import lxml.html
from twisted.internet import reactor, task, defer, protocol
from twisted.python import log
from twisted.words.protocols import irc
from twisted.web.client import getPage
from twisted.application import internet, service
HOST, PORT = 'irc.synirc.net', 6667

class MyFirstIRCProtocol(irc.IRCClient):
    nickname = 'feiji'

    def signedOn(self):
        # This is called once the server has acknowledged that we sent
        # both NICK and USER.
        for channel in self.factory.channels:
            self.join(channel)

    # Obviously, called when a PRIVMSG is received.
    def privmsg(self, user, channel, message):
        nick, _, host = user.partition('!')
        message = message.strip()
        if not message.startswith('!'): # not a trigger command
            return # do nothing
        command, sep, rest = message.lstrip('!').partition(' ')
        # Get the function corresponding to the command given.
        func = getattr(self, 'command_' + command, None)
        # Or, if there was no function, ignore the message.
        if func is None:
            return
        # maybeDeferred will always return a Deferred. It calls func(rest), and
        # if that returned a Deferred, return that. Otherwise, return the return
        # value of the function wrapped in twisted.internet.defer.succeed. If
        # an exception was raised, wrap the traceback in
        # twisted.internet.defer.fail and return that.
        d = defer.maybeDeferred(func, rest)
        # Add callbacks to deal with whatever the command results are.
        # If the command gives error, the _show_error callback will turn the
        # error into a terse message first:
        d.addErrback(self._show_error)
        # Whatever is returned is sent back as a reply:
        if channel == self.nickname:
            # When channel == self.nickname, the message was sent to the bot
            # directly and not to a channel. So we will answer directly too:
            d.addCallback(self._send_message, nick)
        else:
            # Otherwise, send the answer to the channel, and use the nick
            # as addressing in the message itself:
            d.addCallback(self._send_message, channel, nick)

    def _send_message(self, msg, target, nick=None):
        if nick:
            msg = '%s, %s' % (nick, msg)
        self.msg(target, msg)

    def _show_error(self, failure):
        return failure.getErrorMessage()

    def command_ping(self, rest):
        return 'Pong.'

    def command_saylater(self, rest):
        when, sep, msg = rest.partition(' ')
        when = int(when)
        d = defer.Deferred()
        # A small example of how to defer the reply from a command. callLater
        # will callback the Deferred with the reply after so many seconds.
        reactor.callLater(when, d.callback, msg)
        # Returning the Deferred here means that it'll be returned from
        # maybeDeferred in privmsg.
        return d

    def command_title(self, url):
        d = getPage(url)
        # Another example of using Deferreds. twisted.web.client.getPage returns
        # a Deferred which is called back when the URL requested has been
        # downloaded. We add a callback to the chain which will parse the page
        # and extract only the title. If we just returned the deferred instead,
        # the function would still work, but the reply would be the entire
        # contents of the page.
        # After that, we add a callback that will extract the title
        # from the parsed tree lxml returns
        d.addCallback(self._parse_pagetitle, url)
        return d

    def _parse_pagetitle(self, page_contents, url):
        # Parses the page into a tree of elements:
        pagetree = lxml.html.fromstring(page_contents)
        # Extracts the title text from the lxml document using xpath
        title = u' '.join(pagetree.xpath('//title/text()')).strip()
        # Since lxml gives you unicode and unicode data must be encoded
        # to send over the wire, we have to encode the title. Sadly IRC predates
        # unicode, so there's no formal way of specifying the encoding of data
        # transmitted over IRC. UTF-8 is our best bet, and what most people use.
        title = title.encode('utf-8')
        # Since we're returning this value from a callback, it will be passed in
        # to the next callback in the chain (self._send_message).
        return '%s -- "%s"' % (url, title)

class MyFirstIRCFactory(protocol.ReconnectingClientFactory):
    protocol = MyFirstIRCProtocol
    channels = ['#foobartest']

if __name__ == '__main__':
    # This runs the program in the foreground. We tell the reactor to connect
    # over TCP using a given factory, and once the reactor is started, it will
    # open that connection.
    reactor.connectTCP(HOST, PORT, MyFirstIRCFactory())
    # Since we're running in the foreground anyway, show what's happening by
    # logging to stdout.
    log.startLogging(sys.stdout)
    # And this starts the reactor running. This call blocks until everything is
    # done, because this runs the whole twisted mainloop.
    reactor.run()

# This runs the program in the background. __name__ is __builtin__ when you use
# twistd -y on a python module.
elif __name__ == '__builtin__':
    # Create a new application to which we can attach our services. twistd wants
    # an application object, which is how it knows what services should be
    # running. This simplifies startup and shutdown.
    application = service.Application('feiji')
    # twisted.application.internet.TCPClient is how to make a TCP client service
    # which we can attach to the application.
    ircService = internet.TCPClient(HOST, PORT, MyFirstIRCFactory())
    ircService.setServiceParent(application)
    # twistd -y looks for a global variable in this module named 'application'.
    # Since there is one now, and it's all set up, there's nothing left to do.

#!/usr/bin/env python
# -*- coding: utf8 -*-
#
# Chinese IRC botttt.
# Based heavily off of http://www.habnabit.org/twistedex.html
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
from cjklib.cjknife import CharacterInfo
from cjklib.characterlookup import CharacterLookup

HOST, PORT = 'irc.synirc.net', 6667

class FeiJi(irc.IRCClient):
    nickname = 'feiji'
    char_info = CharacterInfo()
    char_lookup = CharacterLookup('C')

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

    # Keep this in case you want to do deferred calls.
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

    def _dict_lookup(self, s):
        return self.char_info.searchDictionary(s.decode('utf8'), 'GR')

    def command_help(self, s):
        return 'https://github.com/ynadji/feiji'

    def command_numstrokes(self, s):
        return ', '.join([str(self.char_lookup.getStrokeCount(x)) for x in s.decode('utf8')])

    def command_pinyin(self, rest):
        """Return pinyin of each character."""
        readings = [u'(' + u', '.join(self.char_lookup.getReadingForCharacter(x, 'Pinyin')) + u')'
                    for x in rest.decode('utf8')]
        res = u'; '.join(readings)
        return res.encode('utf8')

    def command_translate(self, rest):
        """Translate using CEDICT.
        TODO:
            * If you give it a non-phrase group of characters (我妈妈 for
            example) it doesn't have a single dictionary definition. You should
            lookup the longest substring possible that returns a definition,
            shrinking from the right.

            For example: 我妈妈 returns nothing, so you try 我妈 which
            also returns something. Finally, just 我 returns a definition. Next
            you look up 妈妈, which returns a valid definition. Rinse and
            repeat."""
        res = []
        for e in self._dict_lookup(rest):
            foo = u'%s (%s)' % (e.HeadwordSimplified, e.HeadwordTraditional)
            res.append(u'%s (%s): %s' % (e.HeadwordSimplified,
                                         e.HeadwordTraditional,
                                         e.Translation))

        s = u'; '.join(res)
        return s.encode('utf8')

class MyFirstIRCFactory(protocol.ReconnectingClientFactory):
    protocol = FeiJi
    channels = ['#Chinese', '#foobartest']

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

#!/usr/bin/env python
# -*- coding: utf8 -*-
#
# Chinese IRC botttt.
# Based heavily off of http://www.habnabit.org/twistedex.html
#
# Author: Yacin Nadji <yacin@gatech.edu>
#

import sys
from optparse import OptionParser
import lxml.html
from twisted.internet import reactor, task, defer, protocol
from twisted.python import log
from twisted.words.protocols import irc
from twisted.web.client import getPage
from twisted.application import internet, service
from cjklib.cjknife import CharacterInfo
from cjklib.characterlookup import CharacterLookup
from pytranslate import translate as gtranslate

# Command leader/prefix
LEADER = '.'

sys.path.append('nciku')
import nciku

HOST, PORT = 'irc.synirc.net', 6667

class FeiJi(irc.IRCClient):
    nickname = 'feiji'
    char_info = CharacterInfo()
    char_lookup = CharacterLookup('C')
    # Pinyin toolkit manual changes, thanks gents!
    # https://github.com/batterseapower/pinyin-toolkit
    pinyin_toolkit_lookup = {}
    with open('pinyin_toolkit_sydict.u8') as f:
        for line in f:
            line = line.strip().decode('utf8')
            # We only want the first three fields
            trad, simp, pinyin = line.split(' ')[:3]
            # Strip [] and convert to pinyin with tone marks
            pinyin = filter(lambda x: x not in '[]', pinyin)
            pinyin = char_info.convertReading(pinyin, 'Pinyin')
            pinyin_toolkit_lookup[trad] = pinyin
            pinyin_toolkit_lookup[simp] = pinyin

    def _commands(self):
        return zip(*[('h', 'short help'),
                     ('help', 'long help'),
                     ('tr', 'translate'),
                     ('so', 'stroke order'),
                     ('p', 'pinyin'),
                     ('#', 'numstrokes')])

    def isascii(self, s):
        try:
            s.decode('ascii')
            return True
        except UnicodeDecodeError:
            return False

    def signedOn(self):
        # Hacky way to have a command named "#".
        setattr(self, 'command_#', lambda rest: self._numstrokes(rest))

        # This is called once the server has acknowledged that we sent
        # both NICK and USER.
        for channel in self.factory.channels:
            self.join(channel)

    # Obviously, called when a PRIVMSG is received.
    def privmsg(self, user, channel, message):
        nick, _, host = user.partition('!')
        message = message.strip()
        if not message.startswith(LEADER): # not a trigger command
            return # do nothing
        command, sep, rest = message.lstrip(LEADER).partition(' ')

        # We need a special case here because we always want to send directly
        # to the user to reduce chan clutter.
        if command == 'help':
            return self._send_message(self.longhelp(), nick)
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

    def command_h(self, _): return self.shorthelp()
    def shorthelp(self):
        cmds, names = self._commands()
        return 'Commands: (%s)\n.help for more detailed help.' % ' '.join(['.' + x for x in cmds])

    def longhelp(self):
        with open('README') as f:
            return f.read()

    def command_so(self, c): return self._strokes(c)
    def _strokes(self, c):
        return str(nciku.strokeurl(c.decode('utf8')))

    # See def signedOn(self): to see how "command_#" is created.
    def _numstrokes(self, s):
        return ', '.join([str(self.char_lookup.getStrokeCount(x)) for x in s.decode('utf8')])

    def _dict_reading_lookup(self, c):
        """Perform a reading lookup using CEDICT. Return the readings joined
        (hopefully there is only one) or the original character if it couldn't
        be found.

        NOTE: We do .lower() and set() to remove cases like 家 where it returns
        Jiā and jiā for some reason. This should handle most cases where there's
        ambiguity, but certainly not all of them. It looks as though cjklib
        doesn't have a way of resolving this based on context.
        """
        return u','.join(set([e.Reading.lower() for e in self._dict_lookup(c)])) or c

    def command_p(self, rest): return self._pinyin(rest)
    def _pinyin(self, rest):
        """Return pinyin of each character."""
        rest = rest.decode('utf8')
        def reduce_reading((char, readings)):
            """If a character has multiple cjklib readings, use the fine-tuning
            dict from pinyin toolkit and CEDICT as a backup."""
            if len(readings) == 1:
                return readings[0]
            else:
                try:
                    return self.pinyin_toolkit_lookup[char]
                except KeyError:
                    return self._dict_reading_lookup(char)

        readings = [self.char_lookup.getReadingForCharacter(x, 'Pinyin') for x in rest]
        res = u' '.join(map(reduce_reading, zip(rest, readings)))
        return res.encode('utf8')

    def command_tr(self, rest): return self._translate(rest)
    def _translate(self, rest):
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
        try:
            for e in self._dict_lookup(rest):
                foo = u'%s (%s)' % (e.HeadwordSimplified, e.HeadwordTraditional)
                res.append(u'%s (%s): %s' % (e.HeadwordSimplified,
                                             e.HeadwordTraditional,
                                             e.Translation))
        # This sometimes occurs when you search for a string in English to
        # get the Chinese. Ignore it and use Google Translate.
        except TypeError:
            pass

        s = u'; '.join(res)
        # If CEDICT doesn't have anything, resort to Google Translate.
        if s == '':
            if self.isascii(s):
                s = 'google: %s' % gtranslate(rest, sl='english', tl='chinese')
            else:
                s = 'google: %s' % gtranslate(rest, sl='chinese', tl='english')

        # Add pinyin if the query string wasn't ascii
        if not self.isascii(rest):
            s = '%s\n%s' % (s, self._pinyin(rest))
        return s.encode('utf8')

class MyFirstIRCFactory(protocol.ReconnectingClientFactory):
    def __init__(self, channels):
        self.channels = channels
    protocol = FeiJi

def main():
    """main function for standalone usage"""
    usage = "usage: %prog [options] channels"
    parser = OptionParser(usage=usage)

    (options, args) = parser.parse_args()

    if len(args) < 1:
        parser.print_help()
        return 2

    # do stuff
    # This runs the program in the foreground. We tell the reactor to connect
    # over TCP using a given factory, and once the reactor is started, it will
    # open that connection.
    reactor.connectTCP(HOST, PORT, MyFirstIRCFactory(args))
    # Since we're running in the foreground anyway, show what's happening by
    # logging to stdout.
    log.startLogging(sys.stdout)
    # And this starts the reactor running. This call blocks until everything is
    # done, because this runs the whole twisted mainloop.
    reactor.run()

if __name__ == '__main__':
    sys.exit(main())
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

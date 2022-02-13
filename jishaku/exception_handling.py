# -*- coding: utf-8 -*-

"""
jishaku.exception_handling
~~~~~~~~~~~~~~~~~~~~~~~~~~

Functions and classes for handling exceptions.

:copyright: (c) 2021 Devon (Gorialis) R
:license: MIT, see LICENSE for more details.

"""

import asyncio
import subprocess
import traceback
import typing

import discord
from discord.ext import commands

from jishaku.flags import Flags
from jishaku.paginators import PaginatorEmbedInterface


async def send_traceback(bot: commands.Bot, destination: discord.Message, verbosity: int, send_to_author: bool, *exc_info):
    """
    Sends a traceback of an exception to a destination.
    Used when REPL fails for any reason.

    :param destination: Where to send this information to
    :param verbosity: How far back this traceback should go. 0 shows just the last stack.
    :param send_to_author: Whether to send this to the author of the message.
    :param exc_info: Information about this exception, from sys.exc_info or similar.
    :return: The last message sent
    """

    # to make pylint stop moaning
    etype, value, trace = exc_info

    traceback_content = "".join(traceback.format_exception(etype, value, trace, verbosity)).replace("``", "`\u200b`").replace(bot.http.token, "[token omitted]")

    channel = destination.author if send_to_author else destination.channel

    if len(traceback_content) <= 4086:
        return await channel.send(embed=discord.Embed(title="Error", color=discord.Colour.red(), description=f"```py\n{traceback_content}\n```"))

    paginator = commands.Paginator(prefix='```py', max_size=4000)
    for line in traceback_content.split('\n'):
        paginator.add_line(line)

    interface = PaginatorEmbedInterface(bot, paginator, owner=destination.author, embed=discord.Embed(title="Error", color=discord.Colour.red()))
    return await interface.send_to(channel)


async def do_after_sleep(delay: float, coro, *args, **kwargs):
    """
    Performs an action after a set amount of time.

    This function only calls the coroutine after the delay,
    preventing asyncio complaints about destroyed coros.

    :param delay: Time in seconds
    :param coro: Coroutine to run
    :param args: Arguments to pass to coroutine
    :param kwargs: Keyword arguments to pass to coroutine
    :return: Whatever the coroutine returned.
    """
    await asyncio.sleep(delay)
    return await coro(*args, **kwargs)


async def attempt_add_reaction(msg: discord.Message, reaction: typing.Union[str, discord.Emoji])\
        -> typing.Optional[discord.Reaction]:
    """
    Try to add a reaction to a message, ignoring it if it fails for any reason.

    :param msg: The message to add the reaction to.
    :param reaction: The reaction emoji, could be a string or `discord.Emoji`
    :return: A `discord.Reaction` or None, depending on if it failed or not.
    """
    try:
        return await msg.add_reaction(reaction)
    except discord.HTTPException:
        pass


class ReactionProcedureTimer:  # pylint: disable=too-few-public-methods
    """
    Class that reacts to a message based on what happens during its lifetime.
    """
    __slots__ = ('bot', 'message', 'loop', 'handle', 'raised', 'react')

    def __init__(self, bot: commands.Bot, message: discord.Message, loop: typing.Optional[asyncio.BaseEventLoop] = None, react: bool = not Flags.NO_REACTION):
        self.bot = bot
        self.message = message
        self.loop = loop or asyncio.get_event_loop()
        self.handle = None
        self.raised = False
        self.react = react

    async def __aenter__(self):
        if self.react:
            self.handle = self.loop.create_task(do_after_sleep(1, attempt_add_reaction, self.message,
                                                           "\N{BLACK RIGHT-POINTING TRIANGLE}"))
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.handle:
            self.handle.cancel()

        react = self.react

        # no exception, check mark
        if not exc_val and react:
            await attempt_add_reaction(self.message, "\N{WHITE HEAVY CHECK MARK}")
            return

        self.raised = True

        if not react:
            return

        if isinstance(exc_val, (asyncio.TimeoutError, subprocess.TimeoutExpired)):
            # timed out, alarm clock
            await attempt_add_reaction(self.message, "\N{ALARM CLOCK}")
        elif isinstance(exc_val, SyntaxError):
            # syntax error, single exclamation mark
            await attempt_add_reaction(self.message, "\N{HEAVY EXCLAMATION MARK SYMBOL}")
        else:
            # other error, double exclamation mark
            await attempt_add_reaction(self.message, "\N{DOUBLE EXCLAMATION MARK}")


class ReplResponseReactor(ReactionProcedureTimer):  # pylint: disable=too-few-public-methods
    """
    Extension of the ReactionProcedureTimer that absorbs errors, sending tracebacks.
    """

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await super().__aexit__(exc_type, exc_val, exc_tb)

        # nothing went wrong, who cares lol
        if not exc_val:
            return

        if isinstance(exc_val, (SyntaxError, asyncio.TimeoutError, subprocess.TimeoutExpired)):
            # short traceback, send to channel
            verbosity = 0
            send_to_author = False
        else:
            # this traceback likely needs more info, so increase verbosity, and DM it instead.
            verbosity = 8
            send_to_author = False if Flags.NO_DM_TRACEBACK else True

        await send_traceback(
            self.bot, self.message, verbosity, send_to_author, exc_type, exc_val, exc_tb
        )

        return True  # the exception has been handled

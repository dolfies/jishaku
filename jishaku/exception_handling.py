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
import sys
import traceback
import typing
from types import TracebackType

import discord
from discord.ext import commands

from jishaku.flags import Flags
from jishaku.paginators import Interface, MAX_MESSAGE_SIZE


async def send_traceback(
    bot: commands.Bot,
    destination: typing.Union[discord.abc.Messageable, discord.Message],
    verbosity: int,
    etype: typing.Type[BaseException],
    value: BaseException,
    trace: TracebackType,
    owner: typing.Union[discord.User, discord.Member],
):
    """
    Sends a traceback of an exception to a destination.
    Used when REPL fails for any reason.

    :param destination: Where to send this information to
    :param verbosity: How far back this traceback should go. 0 shows just the last stack.
    :param send_to_author: Whether to send this to the author of the message.
    :param exc_info: Information about this exception, from sys.exc_info or similar.
    :return: The last message sent
    """

    traceback_content = "".join(traceback.format_exception(etype, value, trace, verbosity)).replace("``", "`\u200b`")

    if len(traceback_content) <= MAX_MESSAGE_SIZE - 10:
        if Flags.NO_EMBEDS:
            if isinstance(destination, discord.Message):
                return await destination.reply(f"```py\n{traceback_content}\n```")
            return await destination.send(f"```py\n{traceback_content}\n```")
        else:
            if isinstance(destination, discord.Message):
                return await destination.reply(embed=discord.Embed(title="Error", color=discord.Colour.red(), description=f"```py\n{traceback_content}\n```"))
            return await destination.send(embed=discord.Embed(title="Error", color=discord.Colour.red(), description=f"```py\n{traceback_content}\n```"))

    paginator = commands.Paginator(prefix="```py", max_size=MAX_MESSAGE_SIZE - 20)
    for line in traceback_content.split("\n"):
        paginator.add_line(line)

    interface = Interface(bot, paginator, owner=owner, embed=discord.Embed(title="Error", color=discord.Colour.red()))
    return await interface.send_to(destination.channel if isinstance(destination, discord.Message) else destination)


T = typing.TypeVar("T")

if sys.version_info < (3, 10):
    from typing_extensions import ParamSpec

    P = ParamSpec("P")
else:
    P = typing.ParamSpec("P")  # pylint: disable=no-member


async def do_after_sleep(delay: float, coro: typing.Callable[P, typing.Awaitable[T]], *args: P.args, **kwargs: P.kwargs) -> T:
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


async def attempt_add_reaction(msg: discord.Message, reaction: typing.Union[str, discord.Emoji]) -> typing.Optional[discord.Reaction]:
    """
    Try to add a reaction to a message, ignoring it if it fails for any reason.

    :param msg: The message to add the reaction to.
    :param reaction: The reaction emoji, could be a string or `discord.Emoji`
    :return: A `discord.Reaction` or None, depending on if it failed or not.
    """
    if Flags.NO_REACTION:
        return

    try:
        return await msg.add_reaction(reaction)
    except discord.HTTPException:
        pass


class ReplResponseReactor:  # pylint: disable=too-few-public-methods
    """
    Extension of the ReactionProcedureTimer that absorbs errors, sending tracebacks.
    """

    __slots__ = ("bot", "message", "loop", "handle", "raised")

    def __init__(self, bot: commands.Bot, message: discord.Message, loop: typing.Optional[asyncio.BaseEventLoop] = None):
        self.bot = bot
        self.message = message
        self.loop = loop or asyncio.get_event_loop()
        self.handle = None
        self.raised = False

    async def __aenter__(self):
        self.handle = self.loop.create_task(do_after_sleep(2, attempt_add_reaction, self.message, "\N{BLACK RIGHT-POINTING TRIANGLE}"))
        return self

    async def __aexit__(self, exc_type: typing.Type[BaseException], exc_val: BaseException, exc_tb: TracebackType) -> bool:
        if self.handle:
            self.handle.cancel()

        # no exception, check mark
        if not exc_val:
            await attempt_add_reaction(self.message, "\N{WHITE HEAVY CHECK MARK}")
            return False

        self.raised = True

        if isinstance(exc_val, (SyntaxError, asyncio.TimeoutError, subprocess.TimeoutExpired)):
            # short traceback, send to channel
            destination = Flags.traceback_destination(self.message) or self.message.channel

            if destination != self.message.channel:
                await attempt_add_reaction(
                    self.message,
                    # timed out is alarm clock
                    # syntax error is single exclamation mark
                    "\N{HEAVY EXCLAMATION MARK SYMBOL}" if isinstance(exc_val, SyntaxError) else "\N{ALARM CLOCK}",
                )

            await send_traceback(
                self.bot, self.message if destination == self.message.channel else destination, 0, exc_type, exc_val, exc_tb, self.message.author
            )
        else:
            destination = Flags.traceback_destination(self.message) or self.message.author

            if destination != self.message.channel:
                # other error, double exclamation mark
                await attempt_add_reaction(self.message, "\N{DOUBLE EXCLAMATION MARK}")

            # this traceback likely needs more info, so increase verbosity, and DM it instead.
            await send_traceback(
                self.bot, self.message if destination == self.message.channel else destination, 8, exc_type, exc_val, exc_tb, self.message.author
            )

        return True  # the exception has been handled

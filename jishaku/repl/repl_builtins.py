# -*- coding: utf-8 -*-

"""
jishaku.repl.repl_builtins
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Builtin functions and variables within Jishaku REPL contexts.

:copyright: (c) 2021 Devon (Gorialis) R
:license: MIT, see LICENSE for more details.

"""

from typing import Union

import aiohttp
import discord
from discord.ext import commands


async def request(*args, **kwargs) -> Union[bytes, dict]:
    """
    Performs a request against a URL,
    returning the response payload as a dictionary of the response payload interpreted as JSON.

    The arguments to pass are the same as :func:`aiohttp.ClientSession.post`,
    with an additional ``json`` bool which indicates whether to return the result as JSON (defaults to ``True``).
    """

    json = kwargs.pop('json', True)

    async with aiohttp.ClientSession() as session:
        async with session.request(*args, **kwargs) as response:
            response.raise_for_status()

            if json:
                return await response.json()
            return await response.read()


def get_var_dict_from_ctx(ctx: commands.Context, prefix: str = '_'):
    """
    Returns the dict to be used in REPL for a given Context.
    """

    raw_var_dict = {
        'author': ctx.author,
        'bot': ctx.bot,
        'channel': ctx.channel,
        'client': ctx.bot,
        'ctx': ctx,
        'find': discord.utils.find,
        'get': discord.utils.get,
        'guild': ctx.guild,
        'message': ctx.message,
        'msg': ctx.message,
        'request': request,
        'user': ctx.bot.user,
    }

    return {f'{prefix}{k}': v for k, v in raw_var_dict.items()}

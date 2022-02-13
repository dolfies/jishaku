# -*- coding: utf-8 -*-

"""
jishaku.features.shell
~~~~~~~~~~~~~~~~~~~~~~~~

The jishaku shell commands.

:copyright: (c) 2021 Devon (Gorialis) R
:license: MIT, see LICENSE for more details.

"""

from discord.ext import commands

from jishaku.codeblocks import Codeblock, codeblock_converter
from jishaku.exception_handling import ReplResponseReactor
from jishaku.features.baseclass import Feature
from jishaku.paginators import PaginatorEmbedInterface, WrappedPaginator
from jishaku.shell import ShellReader


class ShellFeature(Feature):
    """
    Feature containing the shell-related commands
    """

    @Feature.Command(parent="jsk", name="shell", aliases=["bash", "sh", "powershell", "ps1", "ps", "cmd"])
    async def jsk_shell(self, ctx: commands.Context, *, argument: codeblock_converter):
        """
        Executes statements in the system shell.

        This uses the system shell as defined in $SHELL, or `/bin/bash` otherwise.
        Execution can be cancelled by closing the paginator.
        """

        # Don't use the new ANSI mode if the user is detectably on mobile
        on_mobile = ctx.author.is_on_mobile() if ctx.guild and ctx.bot.intents.presences else False

        async with ReplResponseReactor(ctx.bot, ctx.message):
            with self.submit(ctx):
                with ShellReader(argument.content, escape_ansi=on_mobile) as reader:
                    prefix = "```" + reader.highlight

                    paginator = WrappedPaginator(prefix=prefix, max_size=4000)
                    paginator.add_line(f"{reader.ps1} {argument.content}\n")

                    interface = PaginatorEmbedInterface(ctx.bot, paginator, owner=ctx.author)
                    self.bot.loop.create_task(interface.send_to(ctx))

                    async for line in reader:
                        if interface.closed:
                            return
                        await interface.add_line(line)

                await interface.add_line(f"\n[status] Return code {reader.close_code}")

    @Feature.Command(parent="jsk", name="git")
    async def jsk_git(self, ctx: commands.Context, *, argument: codeblock_converter):
        """
        Shortcut for 'jsk sh git'. Invokes the system shell.
        """

        return await ctx.invoke(self.jsk_shell, argument=Codeblock(argument.language, "git " + argument.content))

    @Feature.Command(parent="jsk", name="pip")
    async def jsk_pip(self, ctx: commands.Context, *, argument: codeblock_converter):
        """
        Shortcut for 'jsk sh pip'. Invokes the system shell.
        """

        return await ctx.invoke(self.jsk_shell, argument=Codeblock(argument.language, "pip " + argument.content))

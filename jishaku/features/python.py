# -*- coding: utf-8 -*-

"""
jishaku.features.python
~~~~~~~~~~~~~~~~~~~~~~~~

The jishaku Python evaluation/execution commands.

:copyright: (c) 2021 Devon (Gorialis) R
:license: MIT, see LICENSE for more details.

"""

import asyncio
import inspect
import io
import sys
import typing

import discord

from jishaku.codeblocks import Codeblock, codeblock_converter
from jishaku.exception_handling import ReplResponseReactor
from jishaku.features.baseclass import Feature
from jishaku.flags import Flags
from jishaku.functools import AsyncSender
from jishaku.paginators import Interface, PaginatorInterface, PaginatorEmbedInterface, MAX_MESSAGE_SIZE, WrappedPaginator, use_file_check
from jishaku.repl import AsyncCodeExecutor, Scope, all_inspections, create_tree, disassemble, get_var_dict_from_ctx
from jishaku.types import ContextA


class PythonFeature(Feature):
    """
    Feature containing the Python-related commands
    """

    def __init__(self, *args: typing.Any, **kwargs: typing.Any):
        super().__init__(*args, **kwargs)
        self._scope = Scope()
        self.retain = Flags.RETAIN
        self.last_result: typing.Any = None
        self.repl_sessions = set()

    @property
    def scope(self):
        """
        Gets a scope for use in REPL.

        If retention is on, this is the internal stored scope,
        otherwise it is always a new Scope.
        """

        if self.retain:
            return self._scope
        return Scope()

    @Feature.Command(parent="jsk", name="retain")
    async def jsk_retain(self, ctx: ContextA, *, toggle: bool = None):  # type: ignore
        """
        Turn variable retention for REPL on or off.
        This does not affect the `jsk repl` command.

        Provide no argument for current status.
        """

        if toggle is None:
            if self.retain:
                return await ctx.send("Variable retention is set to ON.")

            return await ctx.send("Variable retention is set to OFF.")

        if toggle:
            if self.retain:
                return await ctx.send("Variable retention is already set to ON.")

            self.retain = True
            self._scope = Scope()
            return await ctx.send("Variable retention is ON. Future REPL sessions will retain their scope.")

        if not self.retain:
            return await ctx.send("Variable retention is already set to OFF.")

        self.retain = False
        return await ctx.send("Variable retention is OFF. Future REPL sessions will dispose their scope when done.")

    async def jsk_python_result_handling(self, ctx: ContextA, result: typing.Any):  # pylint: disable=too-many-return-statements
        """
        Determines what is done with a result when it comes out of jsk py.
        This allows you to override how this is done without having to rewrite the command itself.
        What you return is what gets stored in the temporary _ variable.
        """

        if isinstance(result, discord.Message) and Flags.REPLACE_MESSAGES:
            result = f"<Message <{result.jump_url}>>"

        if isinstance(result, discord.File):
            return await ctx.send(file=result)

        if isinstance(result, discord.Embed):
            return await ctx.send(embed=result)

        if isinstance(result, (Interface, PaginatorInterface, PaginatorEmbedInterface)):
            return await result.send_to(ctx)

        if not isinstance(result, str):
            # repr all non-strings
            result = repr(result)

        result = result.replace(self.bot.http.token, "[token omitted]")

        # Eventually the below handling should probably be put somewhere else
        if len(result) <= MAX_MESSAGE_SIZE - 10:
            if result.strip() == "":
                result = "\u200b"

            if self.bot.http.token:
                result = result.replace(self.bot.http.token, "[token omitted]")

            if Flags.NO_EMBEDS:
                return await ctx.send(f"```py\n{result}\n```", allowed_mentions=discord.AllowedMentions.none())
            else:
                embed = discord.Embed(title="Result", color=discord.Colour.green(), description=f"```py\n{result}\n```")
                return await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

        if use_file_check(ctx, len(result)):  # File "full content" preview limit
            # Discord's desktop and web client now supports an interactive file content
            #  display for files encoded in UTF-8.
            # Since this avoids escape issues and is more intuitive than pagination for
            #  long results, it will now be prioritized over Interface if the
            #  resultant content is below the filesize threshold
            return await ctx.send(file=discord.File(filename="output.py", fp=io.BytesIO(result.encode("utf-8"))))

        paginator = WrappedPaginator(prefix="```py", suffix="```", max_size=MAX_MESSAGE_SIZE - 20)

        paginator.add_line(result)

        interface = Interface(ctx.bot, paginator, owner=ctx.author)
        return await interface.send_to(ctx)

    def jsk_python_get_convertables(self, ctx: ContextA) -> typing.Tuple[typing.Dict[str, typing.Any], typing.Dict[str, str]]:
        """
        Gets the arg dict and convertables for this scope.

        The arg dict contains the 'locals' to be propagated into the REPL scope.
        The convertables are string->string conversions to be attempted if the code fails to parse.
        """

        arg_dict = get_var_dict_from_ctx(ctx, Flags.SCOPE_PREFIX)
        arg_dict["_"] = self.last_result
        convertables: typing.Dict[str, str] = {}

        for index, user in enumerate(ctx.message.mentions):
            arg_dict[f"__user_mention_{index}"] = user
            convertables[user.mention] = f"__user_mention_{index}"

        for index, channel in enumerate(ctx.message.channel_mentions):
            arg_dict[f"__channel_mention_{index}"] = channel
            convertables[channel.mention] = f"__channel_mention_{index}"

        for index, role in enumerate(ctx.message.role_mentions):
            arg_dict[f"__role_mention_{index}"] = role
            convertables[role.mention] = f"__role_mention_{index}"

        return arg_dict, convertables

    @Feature.Command(parent="jsk", name="py", aliases=["python"])
    async def jsk_python(self, ctx: ContextA, *, argument: codeblock_converter):  # type: ignore
        """
        Direct evaluation of Python code.
        """

        if typing.TYPE_CHECKING:
            argument: Codeblock = argument  # type: ignore

        arg_dict, convertables = self.jsk_python_get_convertables(ctx)
        scope = self.scope

        try:
            async with ReplResponseReactor(ctx.bot, ctx.message):
                with self.submit(ctx):
                    executor = AsyncCodeExecutor(argument.content, scope, arg_dict=arg_dict, convertables=convertables)
                    async for send, result in AsyncSender(executor):  # type: ignore
                        send: typing.Callable[..., None]
                        result: typing.Any

                        if result is None:
                            continue

                        self.last_result = result

                        send(await self.jsk_python_result_handling(ctx, result))

        finally:
            scope.clear_intersection(arg_dict)

    @Feature.Command(parent="jsk", name="repl")
    async def jsk_repl(self, ctx: ContextA):
        """
        Launches a Python interactive shell in the current channel. Messages not starting with "`" will be ignored by default.
        Inspired by R.Danny's implementation (https://github.com/Rapptz/RoboDanny/blob/rewrite/cogs/admin.py).
        """
        arg_dict = get_var_dict_from_ctx(ctx, Flags.SCOPE_PREFIX)
        arg_dict["_"] = self.last_result

        scope = self.scope

        if ctx.channel.id in self.repl_sessions:
            await ctx.send("Already running an interactive shell in this channel. Use `exit()` or `quit()` to exit.")
            return

        banner = (
            "```py\n"
            "Python %s on %s\n"
            'Type "help", "copyright", "credits" or "license" for more information.\n'
            "```" % (sys.version.split("\n")[0], sys.platform)
        )
        self.repl_sessions.add(ctx.channel.id)
        await ctx.send(banner)

        def check(m):
            return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id and (True if Flags.NO_REPL_PREFIX else m.content.startswith("`"))

        while True:
            try:
                response = await self.bot.wait_for("message", check=check, timeout=10.0 * 60.0)
            except asyncio.TimeoutError:
                await ctx.send("Exiting...")
                self.repl_sessions.remove(ctx.channel.id)
                break

            argument = codeblock_converter(response.content)

            if argument.content in ("exit()", "quit()"):
                await ctx.send("Exiting...")
                self.repl_sessions.remove(ctx.channel.id)
                return
            elif argument.content in ("exit", "quit"):
                await ctx.send(f"Use `{argument.content}()` to exit.")
                continue

            arg_dict["message"] = arg_dict["msg"] = response

            try:
                async with ReplResponseReactor(ctx.bot, response):
                    with self.submit(ctx):
                        executor = AsyncCodeExecutor(argument.content, scope, arg_dict=arg_dict)
                        async for send, result in AsyncSender(executor):
                            if result is None:
                                continue

                            self.last_result = result

                            send(await self.jsk_python_result_handling(ctx, result))

            finally:
                scope.clear_intersection(arg_dict)

    @Feature.Command(parent="jsk", name="py_inspect", aliases=["pyi", "python_inspect", "pythoninspect"])
    async def jsk_python_inspect(self, ctx: ContextA, *, argument: codeblock_converter):  # type: ignore
        """
        Evaluation of Python code with inspect information.
        """

        if typing.TYPE_CHECKING:
            argument: Codeblock = argument  # type: ignore

        arg_dict, convertables = self.jsk_python_get_convertables(ctx)
        scope = self.scope

        try:
            async with ReplResponseReactor(ctx.bot, ctx.message):
                with self.submit(ctx):
                    executor = AsyncCodeExecutor(argument.content, scope, arg_dict=arg_dict, convertables=convertables)
                    async for send, result in AsyncSender(executor):  # type: ignore
                        send: typing.Callable[..., None]
                        result: typing.Any

                        self.last_result = result

                        header = repr(result).replace("``", "`\u200b`")

                        if self.bot.http.token:
                            header = header.replace(self.bot.http.token, "[token omitted]")

                        if len(header) > 485:
                            header = header[0:482] + "..."

                        lines = [f"=== {header} ===", ""]

                        for name, res in all_inspections(result):
                            lines.append(f"{name:16.16} :: {res}")

                        docstring = (inspect.getdoc(result) or "").strip()

                        if docstring:
                            lines.append(f"\n=== Help ===\n\n{docstring}")

                        text = "\n".join(lines)

                        if use_file_check(ctx, len(text)):  # File "full content" preview limit
                            send(await ctx.send(file=discord.File(filename="inspection.prolog", fp=io.BytesIO(text.encode("utf-8")))))
                        else:
                            paginator = WrappedPaginator(prefix="```prolog", max_size=MAX_MESSAGE_SIZE - 20)

                            paginator.add_line(text)

                            interface = Interface(ctx.bot, paginator, owner=ctx.author)
                            send(await interface.send_to(ctx))
        finally:
            scope.clear_intersection(arg_dict)

    @Feature.Command(parent="jsk", name="dis", aliases=["disassemble"])
    async def jsk_disassemble(self, ctx: ContextA, *, argument: codeblock_converter):  # type: ignore
        """
        Disassemble Python code into bytecode.
        """

        if typing.TYPE_CHECKING:
            argument: Codeblock = argument  # type: ignore

        arg_dict = get_var_dict_from_ctx(ctx, Flags.SCOPE_PREFIX)

        async with ReplResponseReactor(ctx.bot, ctx.message):
            text = "\n".join(disassemble(argument.content, arg_dict=arg_dict))

            if use_file_check(ctx, len(text)):  # File "full content" preview limit
                await ctx.send(file=discord.File(filename="dis.py", fp=io.BytesIO(text.encode("utf-8"))))
            else:
                paginator = WrappedPaginator(prefix="```py", max_size=MAX_MESSAGE_SIZE - 20)

                paginator.add_line(text)

                interface = Interface(ctx.bot, paginator, owner=ctx.author)
                await interface.send_to(ctx)

    @Feature.Command(parent="jsk", name="ast")
    async def jsk_ast(self, ctx: ContextA, *, argument: codeblock_converter):  # type: ignore
        """
        Disassemble Python code into AST.
        """

        if typing.TYPE_CHECKING:
            argument: Codeblock = argument  # type: ignore

        async with ReplResponseReactor(ctx.bot, ctx.message):
            text = create_tree(argument.content, use_ansi=Flags.use_ansi(ctx))

            await ctx.send(file=discord.File(filename="ast.ansi", fp=io.BytesIO(text.encode("utf-8"))))

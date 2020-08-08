import os
import re
from json import dumps
from typing import Optional, List

import requests
from discord import Embed, Guild, Status, Game, Member, Message
from discord import Role
from discord.ext import commands, tasks
from discord.ext.commands import Cog, Bot, guild_only, Context, UserInputError

from database import run_in_thread, db
from models.allowed_invite import AllowedInvite
from models.btp_role import BTPRole
from models.settings import Settings
from translations import translations
from util import read_normal_message


class InfoCog(Cog, name="Server Information"):
    def __init__(self, bot: Bot):
        self.bot = bot
        self.current_status = 0

    async def on_ready(self):
        try:
            self.status_loop.start()
        except RuntimeError:
            self.status_loop.restart()
        return True

    async def on_message(self, message: Message) -> bool:
        if message.guild is None:
            return True

        for line in message.content.splitlines():
            if re.match(r"^> .*<@&\d+>.*$", line):
                await message.channel.send(translations.f_quote_remove_mentions(message.author.mention))
                break
        return True

    @tasks.loop(seconds=20)
    async def status_loop(self):
        await self.bot.change_presence(
            status=Status.online, activity=Game(name=translations.profile_status[self.current_status])
        )
        self.current_status = (self.current_status + 1) % len(translations.profile_status)

    @commands.command(name="bugreport", aliases=["bug", "b"])
    async def bug_report(self, ctx: Context):
        await ctx.send("Now send the full bug report in one message.")

        content, files = await read_normal_message(self.bot, ctx.channel, ctx.author)
        new_content = ctx.author.mention + " reported:\n" + content
        data = {"username": ctx.author.display_name, "avatar_url": str(ctx.author.avatar_url), "content": new_content}
        payload = {"payload_json": dumps(data)}
        multipart = {}
        for i, file in enumerate(files):
            multipart[str(i)] = (file.filename, file.fp)

        result = requests.post(os.environ["BUG_REPORT_URL"], data=payload, files=multipart)

        try:
            result.raise_for_status()
        except requests.exceptions.HTTPError as err:
            print(err)
        else:
            print("Payload delivered successfully, code {}.".format(result.status_code))

    @commands.group(name="server")
    @guild_only()
    async def server(self, ctx: Context):
        """
        displays information about this discord server
        """

        if ctx.subcommand_passed is not None:
            if ctx.invoked_subcommand is None:
                raise UserInputError
            return

        guild: Guild = ctx.guild
        embed = Embed(title=guild.name, description=translations.info_description, color=0x005180)
        embed.set_thumbnail(url=guild.icon_url)
        created = guild.created_at.date()
        embed.add_field(name=translations.creation_date, value=f"{created.day}.{created.month}.{created.year}")
        online_count = sum([m.status != Status.offline for m in guild.members])
        embed.add_field(
            name=translations.f_cnt_members(guild.member_count), value=translations.f_cnt_online(online_count)
        )
        embed.add_field(name=translations.owner, value=guild.owner.mention)

        async def get_role(role_name) -> Optional[Role]:
            return guild.get_role(await run_in_thread(Settings.get, int, role_name + "_role"))

        role: Role
        if (role := await get_role("admin")) is not None and role.members:
            embed.add_field(
                name=translations.f_cnt_admins(len(role.members)),
                value="\n".join(":small_orange_diamond: " + m.mention for m in role.members),
            )
        if (role := await get_role("mod")) is not None and role.members:
            embed.add_field(
                name=translations.f_cnt_mods(len(role.members)),
                value="\n".join(":small_orange_diamond: " + m.mention for m in role.members),
            )
        if (role := await get_role("supp")) is not None and role.members:
            embed.add_field(
                name=translations.f_cnt_supps(len(role.members)),
                value="\n".join(":small_orange_diamond: " + m.mention for m in role.members),
            )

        bots = [m for m in guild.members if m.bot]
        bots_online = sum([m.status != Status.offline for m in bots])
        embed.add_field(name=translations.f_cnt_bots(len(bots)), value=translations.f_cnt_online(bots_online))
        embed.add_field(
            name=translations.topics, value=translations.f_cnt_topics(len(await run_in_thread(db.all, BTPRole)))
        )
        embed.add_field(
            name=translations.allowed_discord_server,
            value=translations.f_cnt_servers_whitelisted(len(await run_in_thread(db.all, AllowedInvite))),
        )

        await ctx.send(embed=embed)

    @server.command(name="bots")
    async def list_bots(self, ctx: Context):
        """
        list all bots on the server
        """

        guild: Guild = ctx.guild
        embed = Embed(title=translations.bots, color=0x005180)
        online: List[Member] = []
        offline: List[Member] = []
        for member in guild.members:  # type: Member
            if member.bot:
                [offline, online][member.status != Status.offline].append(member)

        if not online + offline:
            embed.colour = 0xCF0606
            embed.description = translations.no_bots
            await ctx.send(embed=embed)
            return

        if online:
            embed.add_field(
                name=translations.online, value="\n".join(":small_orange_diamond: " + m.mention for m in online)
            )
        if offline:
            embed.add_field(
                name=translations.offline, value="\n".join(":small_blue_diamond: " + m.mention for m in offline)
            )
        await ctx.send(embed=embed)

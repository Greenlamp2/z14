import asyncio
import functools
import struct

import discord
import nacl
from discord import VoiceClient
from discord.ext import commands
from .recorder import Recorder


class Record(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.voice_channel_id = None
        self.voice_client = None
        self.recorder = Recorder()
        self.recorder.start()

    @commands.Cog.listener()
    async def on_ready(self):
        print('Logged in as {0} (ID: {0.id})'.format(self.bot.user))

        await self.set_voice_channel(804323830696640527)

    @commands.Cog.listener()
    async def on_voice_server_update(self, *args):
        print('coucou')
        self.recorder.receive_packet(*args)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        print('on_voice_state_update')
        try:
            if before.voice_channel != after.voice_channel:
                if before.voice_channel and before.voice_channel.id == self.voice_channel_id:
                    self.send_call("on_leave_voice_channel", before)

                elif after.voice_channel.id == self.voice_channel_id:
                    self.send_call("on_join_voice_channel", after)

        except AttributeError:
            pass

    @commands.Cog.listener()
    async def on_speak(self, *args):
        self.recorder.receive_packet(*args)

    @commands.Cog.listener()
    async def set_voice_channel(self, id):
        if self.voice_client and self.voice_client.is_connected():
            if self.voice_channel_id == id:
                print("already connected")
                return
            else:
                print("disconnecting voice client")
                await self.voice_client.disconnect()

        self.voice_channel_id = id
        if not self.voice_channel_id:
            self.voice_client = None
            return

        self.recorder.reset()

        print("joining voice channel")

        channel = self.bot.get_channel(self.voice_channel_id)
        self.voice_client = await channel.connect()
        self.voice_client.listen()

        # self.ws = self.voice_client.connect_websocket
        # await self.voice_client.guild.change_voice_state(channel=channel)

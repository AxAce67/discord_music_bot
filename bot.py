import discord
from discord import ui
from discord.ext import commands, tasks  # tasksを追加
import yt_dlp as youtube_dl
import asyncio
from collections import deque
import os
from dotenv import load_dotenv
import concurrent.futures
from discord import app_commands
import datetime
import traceback
import psutil
import time
import platform
import json
import pytz  # タイムゾーン処理のためにpytzをインポート

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

# ファイルの先頭付近（importの後）に以下を追加
BOT_VERSION = "1.0.0"  # ボットのバージョンを定義
OWNER_ID = '743756005862539344'  # ここにあなたのDiscord IDを入力してください

# YouTubeダウンロードのオプション
ydl_opts = {
    'format': 'bestaudio/best',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '192',
    }],
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0'
}

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        ydl_opts = {
            'format': 'bestaudio/best',
            'nocheckcertificate': True,
            'ignoreerrors': False,
            'logtostderr': False,
            'quiet': True,
            'no_warnings': True,
            'default_search': 'auto',
            'source_address': '0.0.0.0',
        }
        
        with youtube_dl.YoutubeDL(ydl_opts) as ydl:
            try:
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    video_id = await loop.run_in_executor(executor, cls.extract_video_id, url)
                    if video_id:
                        info = await loop.run_in_executor(executor, lambda: ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False))
                    else:
                        info = await loop.run_in_executor(executor, lambda: ydl.extract_info(url, download=False))
            except Exception as e:
                raise Exception(f"Could not extract info from {url}: {e}")

        if 'entries' in info:
            data = info['entries'][0]
        else:
            data = info

        filename = data['url']
        ffmpeg_options = {
            'options': '-vn -bufsize 64k',
            'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
        }
        return cls(discord.FFmpegPCMAudio(filename, executable="C:\\ffmpeg\\ffmpeg-master-latest-win64-gpl-shared\\bin\\ffmpeg.exe", **ffmpeg_options), data=data)

    @staticmethod
    def extract_video_id(url):
        # URLからビデオIDを抽出するメソッド
        import re
        patterns = [
            r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',
            r'(?:embed\/|v\/|youtu.be\/)([0-9A-Za-z_-]{11})',
            r'(?:watch\?v=|\&v=)([0-9A-Za-z_-]{11})'
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

class StatusView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot
        self.message = None

    @discord.ui.button(label="更新", style=discord.ButtonStyle.primary, custom_id="status_update")
    async def update_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.update_status(interaction)

    async def update_status(self, interaction=None):
        embed = create_status_embed(self.bot)
        if self.message:
            try:
                await self.message.edit(embed=embed, view=self)
                if interaction:
                    await interaction.followup.send("ステータスを更新しました。", ephemeral=True)
            except discord.errors.NotFound:
                # メッセージが見つからない場合は新しいメッセージを送信
                if interaction:
                    self.message = await interaction.followup.send(embed=embed, view=self)
                else:
                    self.message = await interaction.channel.send(embed=embed, view=self)
        elif interaction:
            self.message = await interaction.followup.send(embed=embed, view=self)

@tasks.loop(minutes=1)
async def update_status_task(view: StatusView):
    try:
        await view.update_status()
    except Exception as e:
        print(f"Error in update_status_task: {e}")
        update_status_task.stop()

def create_status_embed(bot):
    embed = discord.Embed(title="Bot Status", color=COLORS['info'])
    
    # OS情報
    embed.add_field(name="OS Information", value=f"{platform.system()} {platform.release()}", inline=False)
    
    # CPU使用率
    cpu_percent = psutil.cpu_percent()
    cpu_bar = "■" * int(cpu_percent / 5) + "□" * (20 - int(cpu_percent / 5))
    embed.add_field(name="CPU Status", value=f"`{cpu_bar}` {cpu_percent}%", inline=False)
    
    # メモリ使用率
    memory = psutil.virtual_memory()
    memory_percent = memory.percent
    memory_bar = "■" * int(memory_percent / 5) + "□" * (20 - int(memory_percent / 5))
    embed.add_field(name="Memory Status", value=f"`{memory_bar}` {memory_percent}%\n"
                    f"{memory.used / 1024 / 1024:.0f} MB / {memory.total / 1024 / 1024:.0f} MB", inline=False)
    
    # Shard情報
    if hasattr(bot, 'shards'):
        embed.add_field(name="Shard Information", value=f"Total: {bot.shard_count}, Running: {len(bot.shards)}, Queued: 0", inline=False)
    else:
        embed.add_field(name="Shard Information", value="Sharding not enabled", inline=False)
    
    # バージョン情報
    embed.add_field(name="Version", value=f"{discord.__version__}", inline=True)
    
    # 参加しているボイスチャンネル数
    voice_channels = sum(1 for guild in bot.guilds for vc in guild.voice_channels if bot.user in vc.members)
    embed.add_field(name="Joined VoiceChannels", value=str(voice_channels), inline=True)
    
    # 稼働時間
    uptime = time.time() - bot.start_time
    hours, remainder = divmod(int(uptime), 3600)
    minutes, seconds = divmod(remainder, 60)
    days, hours = divmod(hours, 24)
    embed.add_field(name="Uptime", value=f"{days}d {hours}h {minutes}m {seconds}s", inline=True)

    # 最終更新時刻
    embed.set_footer(text=f"最終更新: {discord.utils.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")

    return embed

# ファイルの先頭付に追加
def load_log_channel():
    try:
        with open('log_channel.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return None

def save_log_channel(channel_id):
    with open('log_channel.json', 'w') as f:
        json.dump(channel_id, f)

log_channel_id = load_log_channel()

# 既存のインポートに追加
from discord.ext import commands

# on_ready イベントハンドラを修正
@bot.event
async def on_ready():
    ascii_art = """
██████╗  █████╗ ██╗   ██╗    ███╗   ███╗██╗   ██╗███████╗██╗ ██████╗
██╔══██╗██╔══██╗╚██╗ ██╔╝    ████╗ ████║██║   ██║██╔════╝██║██╔════╝
██████╔╝███████║ ╚████╔╝     ██╔████╔██║██║   ██║███████╗██║██║     
██╔══██╗██╔══██║  ╚██╔╝      ██║╚██╔╝██║██║   ██║╚════██║██║██║     
██║  ██║██║  ██║   ██║       ██║ ╚═╝ ██║╚██████╔╝███████║██║╚██████╗
╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝       ╚═╝     ╚═╝ ╚═════╝ ╚══════╝╚═╝ ╚═════╝
    """
    print(ascii_art)
    print(f'{bot.user} としてログインしました。')

    # 起動ログを送信
    global log_channel_id
    if log_channel_id:
        channel = bot.get_channel(log_channel_id)
        if channel:
            utc_now = datetime.datetime.now(pytz.UTC)
            embed = discord.Embed(title="起動完了", color=COLORS['success'])
            embed.description = f"Ray Musicが起動しました。全システム正常稼働中。"
            embed.add_field(name="サーバー数", value=f"{len(bot.guilds)}", inline=True)
            embed.add_field(name="ユーザー数", value=f"{sum(guild.member_count for guild in bot.guilds)}", inline=True)
            embed.set_footer(text=f"{utc_now.strftime('%Y-%m-%d %H:%M:%S')} UTC | バージョン: {BOT_VERSION}")
            await channel.send(embed=embed)
        else:
            print(f"警告: ログチャンネル (ID: {log_channel_id}) が見つかりません。")

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
        
        # デバッグ情報を追加
        print("登録されたスラッシュコマンド:")
        for cmd in bot.tree.get_commands():
            print(f"- /{cmd.name}: {cmd.description}")
    except Exception as e:
        print(f"コマンドの同期に失敗しました: {e}")

    # ステータス更新タスクを開始
    update_status.start()

    # ボットの起動時刻を記録
    bot.start_time = time.time()

    # ボットの起動時にViewを追加
    bot.add_view(StatusView(bot))

    # ヘルプ用の埋め込みを定義
    embed1 = discord.Embed(title="ヘルプ (1/2)", description="利用可能なコマンド一覧", color=COLORS['info'])
    # embed1 のフィールドを追加

    embed2 = discord.Embed(title="ヘルプ (2/2)", description="利用可能なコマンド一覧", color=COLORS['info'])
    # embed2 のフィールドを追加

    # ボットの起動時にHelpViewを追加
    bot.add_view(HelpView([embed1, embed2]))

@tasks.loop(minutes=1)  # 1分ごとに更新
async def update_status():
    total_users = sum(guild.member_count for guild in bot.guilds)
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.playing,
        name=f"/help | {len(bot.guilds)} Servers / {total_users} Users"
    ))

@update_status.before_loop
async def before_update_status():
    await bot.wait_until_ready()

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        # コマンドが見つからない場合は何もしない
        return
    else:
        embed = discord.Embed(title="エラー", description=f"{error}", color=COLORS['error'])
        await ctx.send(embed=embed)

@bot.command()
async def join(ctx):
    """ボイスチャンネルに参加し、スピーカーミュートにする"""
    if ctx.author.voice is None:
        embed = discord.Embed(title="エラー", description="あなたはボイスチャンネルに接続していません。", color=COLORS['error'])
        await ctx.send(embed=embed)
        return
    
    channel = ctx.author.voice.channel
    
    if ctx.voice_client is not None:
        if ctx.voice_client.channel == channel:
            embed = discord.Embed(title="エラー", description=f"既に {channel.mention} に接続しています。", color=COLORS['error'])
            await ctx.send(embed=embed)
            return
        await ctx.voice_client.move_to(channel)
    else:
        await channel.connect()
    
    await set_speaker_mute(ctx.guild, True)
    embed = discord.Embed(title="ボイスチャンネル接続", description=f"{channel.mention} に接続しました。", color=COLORS['success'])
    await ctx.send(embed=embed)

async def set_speaker_mute(guild, mute):
    """ボットのスピーカーミュート状態を設定する"""
    voice_client = guild.voice_client
    if voice_client and voice_client.is_connected():
        await guild.change_voice_state(channel=voice_client.channel, self_mute=False, self_deaf=mute)

@bot.command()
async def leave(ctx):
    """ボイスチャンネルから退出"""
    if ctx.voice_client is None:
        embed = discord.Embed(title="エラー", description="ボットはボイスチャンネルに接続していません。", color=COLORS['error'])
        await ctx.send(embed=embed)
        return
    channel = ctx.voice_client.channel
    
    # 断フラグを設定
    bot.is_leaving = True
    
    await ctx.voice_client.disconnect()
    embed = discord.Embed(title="ボイスチャンネル退出", description=f"{channel.mention} から退出しました。", color=COLORS['info'])
    await ctx.send(embed=embed)

# 色の定義を更新
COLORS = {
    'success': 0x1DB954,  # Spotify緑
    'error': 0xE74C3C,    # 赤
    'info': 0x3498DB,     # 青
    'warning': 0xF1C40F,  # 黄色
    'music': 0x1DB954,    # Spotifyに変更（以前の紫から
}

@bot.command()
async def play(ctx, *, url):
    """指定された曲を再生またはキューに追加"""
    global track_queues
    
    async with ctx.typing():
        if ctx.voice_client is None:
            if ctx.author.voice:
                await ctx.author.voice.channel.connect()
                await set_speaker_mute(ctx.guild, True)
            else:
                embed = discord.Embed(title="エラー", description="ボイスチャンネルに接続してください。", color=COLORS['error'])
                await ctx.send(embed=embed)
                return
        
        if ctx.guild.id not in track_queues:
            track_queues[ctx.guild.id] = deque()

        try:
            player = await YTDLSource.from_url(url, loop=bot.loop, stream=True)
            
            duration = player.data.get('duration')
            duration_str = f"{duration // 60:02d}:{duration % 60:02d}" if duration else "不明"
            
            if ctx.voice_client.is_playing():
                # 既に再生中の場合キューに追加
                track_queues[ctx.guild.id].append(player)
                position = len(track_queues[ctx.guild.id])
                
                # キュの合計時間計算
                queue_duration = sum(track.data.get('duration', 0) for track in track_queues[ctx.guild.id])
                estimated_time = f"{queue_duration // 3600:02d}:{(queue_duration % 3600) // 60:02d}:{queue_duration % 60:02d}"
                
                embed = discord.Embed(title="トラック追加", color=COLORS['music'])
                embed.description = f"**[{player.title}]({player.data.get('webpage_url')})**"
                embed.add_field(name="再生時間", value=duration_str, inline=True)
                embed.add_field(name="キュー内の位置", value=f"#{position}", inline=True)
                embed.add_field(name="再生までの推定時間", value=estimated_time, inline=True)
                embed.set_thumbnail(url=player.data.get('thumbnail'))
                embed.set_footer(text=f"リクエス: {ctx.author.display_name}", icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
            else:
                # 再生中でない場合は直接再生
                ctx.voice_client.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop))
                embed = discord.Embed(title="再生中", color=COLORS['success'])
                embed.description = f"**[{player.title}]({player.data.get('webpage_url')})**"
                embed.add_field(name="再生時間", value=duration_str, inline=True)
                embed.set_thumbnail(url=player.data.get('thumbnail'))
                embed.set_footer(text=f"リクエスト: {ctx.author.display_name}", icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
            
            await ctx.send(embed=embed)
        except Exception as e:
            print(f"Error in play command: {e}")
            print(traceback.format_exc())
            embed = discord.Embed(title="エラー", description=f"再生中にエラーが発生しました: {str(e)}", color=COLORS['error'])
            await ctx.send(embed=embed)

# ループ状態を保持すたの辞書
loop_states = {}

@bot.command()
async def loop(ctx, state: str = None):
    """ープ再生を設定する"""
    global loop_states
    if ctx.voice_client is None or not ctx.voice_client.is_playing():
        embed = discord.Embed(title="エラー", description="現在再生中の曲がありません。", color=COLORS['error'])
        await ctx.send(embed=embed)
        return

    current_state = loop_states.get(ctx.guild.id, False)

    if state is None:
        # 引数がない場合現在の状態を切り替える
        new_state = not current_state
    elif state.lower() in ['on', 'オン', 'true', '1']:
        new_state = True
    elif state.lower() in ['off', 'オフ', 'false', '0']:
        new_state = False
    else:
        embed = discord.Embed(title="エラー", description="効な引数です。'on' または 'off' を指定してください。", color=COLORS['error'])
        await ctx.send(embed=embed)
        return

    loop_states[ctx.guild.id] = new_state
    state_str = "有効" if new_state else "無効"
    embed = discord.Embed(title="ループ再生", description=f"ループ再生が{state_str}になりました。", color=COLORS['info'])
    await ctx.send(embed=embed)

@bot.command()
async def stop(ctx):
    """再生を停止する"""
    if ctx.voice_client:
        ctx.voice_client.stop()
        if ctx.guild.id in track_queues:
            track_queues[ctx.guild.id].clear()
        embed = discord.Embed(title="音楽停止", description="再生を停止しました。", color=COLORS['warning'])
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(title="エラー", description="ボットはボイスチャンネルに接続していません。", color=COLORS['error'])
        await ctx.send(embed=embed)

@bot.command()
async def track(ctx):
    """現在のトラックキューを表示"""
    if ctx.guild.id not in track_queues or (len(track_queues[ctx.guild.id]) == 0 and not ctx.voice_client.is_playing()):
        embed = discord.Embed(title="再生リスト", description="現在の再生リストは空です", color=COLORS['info'])
        await ctx.send(embed=embed)
        return

    embed = discord.Embed(title="再生リスト", color=COLORS['music'])
    # 再生中の曲を表示
    if ctx.voice_client and ctx.voice_client.is_playing():
        current_track = ctx.voice_client.source
        duration = current_track.data.get('duration')
        duration_str = f"{duration // 60:02d}:{duration % 60:02d}" if duration else "不明"
        embed.add_field(name="再生中", value=f"[{current_track.title}]({current_track.data.get('webpage_url')}) - `{duration_str}`", inline=False)
        embed.set_thumbnail(url=current_track.data.get('thumbnail'))

    # キューの曲を表示
    if track_queues[ctx.guild.id]:
        queue_list = []
        total_duration = 0
        for i, track in enumerate(track_queues[ctx.guild.id], start=1):
            duration = track.data.get('duration', 0)
            total_duration += duration
            duration_str = f"{duration // 60:02d}:{duration % 60:02d}" if duration else "不明"
            queue_list.append(f"`{i}.` [{track.title}]({track.data.get('webpage_url')}) - `{duration_str}`")

        embed.add_field(name="キュー", value="\n".join(queue_list[:5]), inline=False)  # 最初の5曲のみ表示
        if len(queue_list) > 5:
            embed.add_field(name="", value=f"... 他 {len(queue_list) - 5} 曲", inline=False)

        total_duration_str = f"{total_duration // 3600:02d}:{(total_duration % 3600) // 60:02d}:{total_duration % 60:02d}"
        embed.add_field(name="キュー情報", value=f"総曲数: {len(queue_list)}\n総再生時間: `{total_duration_str}`", inline=False)

    # サムネイルをキューの最初の曲に設定（再生中の曲がない場）
    if not ctx.voice_client.is_playing() and track_queues[ctx.guild.id]:
        embed.set_thumbnail(url=track_queues[ctx.guild.id][0].data.get('thumbnail'))

    await ctx.send(embed=embed)

# トラックキューを保持するための辞書をグロバル変数として定義
track_queues = {}

class HelpView(ui.View):
    def __init__(self, embeds):
        super().__init__(timeout=None)  # タイムアウトを無効にする
        self.embeds = embeds
        self.current_page = 0
        
        # サポートサーバーへのリンクボタンを追加
        self.add_item(discord.ui.Button(label="サポートサーバー", style=discord.ButtonStyle.link, url="https://discord.gg/5456yBmZXT"))

    @ui.button(label="前のページ", style=discord.ButtonStyle.gray, disabled=True, custom_id="help_previous")
    async def previous_button(self, interaction: discord.Interaction, button: ui.Button):
        self.current_page = max(0, self.current_page - 1)
        await self.update_message(interaction)

    @ui.button(label="次のページ", style=discord.ButtonStyle.gray, custom_id="help_next")
    async def next_button(self, interaction: discord.Interaction, button: ui.Button):
        self.current_page = min(len(self.embeds) - 1, self.current_page + 1)
        await self.update_message(interaction)

    async def update_message(self, interaction: discord.Interaction):
        embed = self.embeds[self.current_page]
        self.previous_button.disabled = (self.current_page == 0)
        self.next_button.disabled = (self.current_page == len(self.embeds) - 1)
        await interaction.response.edit_message(embed=embed, view=self)

@bot.tree.command(name="help", description="使い方とコマンド一覧を表示")
async def slash_help(interaction: discord.Interaction):
    embed1 = discord.Embed(title="ヘルプ (1/2)", description="利用可能コマンド一覧", color=COLORS['info'])
    embed1.add_field(name="!join", value="ボイスチャンネルに参加します。", inline=False)
    embed1.add_field(name="!leave", value="ボイスチャネルから退出します。", inline=False)
    embed1.add_field(name="!play <URL>", value="指定された曲を再生またはキューに追加します。", inline=False)
    embed1.add_field(name="!stop", value="再生を全に停止し、キューをクリアします。", inline=False)
    embed1.add_field(name="!skip", value="現在の曲をスキップし、次の曲を再生ます。", inline=False)
    embed1.add_field(name="!track", value="現在のトラックキューを表示します。", inline=False)

    embed2 = discord.Embed(title="ヘルプ (2/2)", description="利用可能コマンド一覧", color=COLORS['info'])
    embed2.add_field(name="!loop [on/off]", value="ループ再生を設定します。引数なしで現在の状態を切り替え、'on'または'off'で明示的設定します。", inline=False)
    embed2.add_field(name="/help", value="このヘルプメッセージを表示します。", inline=False)
    embed2.add_field(name="/userstatus [ユーザー]", value="指定したユーザー（または自分）のステータスを表示します。", inline=False)
    embed2.add_field(name="/serverstatus", value="現在のサーバーのステータスを表示します。", inline=False)
    embed2.add_field(name="/status", value="ボットのリアルタイムステータスを表示します。", inline=False)

    view = HelpView([embed1, embed2])
    await interaction.response.send_message(embed=embed1, view=view)

@bot.command()
async def skip(ctx):
    """現在の曲をスキップし、次の曲を再生する"""
    if ctx.voice_client is None:
        embed = discord.Embed(title="エラー", description="ボットはボイスチャンネルに接続していません。", color=COLORS['error'])
        await ctx.send(embed=embed)
        return

    if not ctx.voice_client.is_playing():
        embed = discord.Embed(title="エラー", description="現在再生中の曲がありません。", color=COLORS['error'])
        await ctx.send(embed=embed)
        return

    ctx.voice_client.stop()
    await play_next(ctx, skip=True, command_skip=True)

async def play_next(ctx, skip=False, command_skip=False):
    global track_queues, loop_states
    if ctx.voice_client is None:
        return

    if ctx.guild.id in loop_states and loop_states[ctx.guild.id] and not skip:
        # ループ再生が有効で、スキップでない場合、同じ曲を再
        current_source = ctx.voice_client.source
        if current_source:
            new_source = await YTDLSource.from_url(current_source.data['webpage_url'], loop=bot.loop, stream=True)
            ctx.voice_client.play(new_source, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop))
            embed = discord.Embed(title="ループ再生中", color=COLORS['music'])
            embed.description = f"**[{new_source.title}]({new_source.data.get('webpage_url')})**"
            duration = new_source.data.get('duration')
            duration_str = f"{duration // 60:02d}:{duration % 60:02d}" if duration else "不明"
            embed.add_field(name="再生時間", value=duration_str, inline=True)
            embed.set_thumbnail(url=new_source.data.get('thumbnail'))
            await ctx.send(embed=embed)
    elif ctx.guild.id in track_queues and len(track_queues[ctx.guild.id]) > 0:
        # 次の曲を再生（キューから削除せずに再生）
        next_player = track_queues[ctx.guild.id][0]
        ctx.voice_client.play(next_player, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop))
        embed = discord.Embed(title="再生中", color=COLORS['music'])
        embed.description = f"**[{next_player.title}]({next_player.data.get('webpage_url')})**"
        duration = next_player.data.get('duration')
        duration_str = f"{duration // 60:02d}:{duration % 60:02d}" if duration else "不明"
        embed.add_field(name="再生時間", value=duration_str, inline=True)
        embed.set_thumbnail(url=next_player.data.get('thumbnail'))
        await ctx.send(embed=embed)
        
        # スキップの場合のみ、再生開始後にキューから削除
        if skip:
            track_queues[ctx.guild.id].popleft()
    else:
        # キューが空の場合
        if command_skip:
            embed = discord.Embed(title="再生終了", description="キューが空になりました。", color=COLORS['info'])
            await ctx.send(embed=embed)
        ctx.voice_client.stop()

    # ボイスャンネルからは切しない

# グローバル変数として、イマーを保持する辞書を追加
voice_state_timers = {}

# グローバル変数として、最後にコマンドが実行されたチャンネルを保存する辞書を追加
last_command_channels = {}

@bot.event
async def on_command(ctx):
    # コマンドが実行されるたびに、そのチャンネルを記録
    last_command_channels[ctx.guild.id] = ctx.channel

@bot.event
async def on_voice_state_update(member, before, after):
    if member == bot.user:
        if before.channel and not after.channel:
            # ボットがボイスチャンネルから切断された場合
            guild = before.channel.guild
            
            # ボットが自分で切断したかどうかを確認
            if not hasattr(bot, 'is_leaving') or not bot.is_leaving:
                # 自動切断の場合はメッセージを送信しない
                pass
            
            # フラグをリセット
            bot.is_leaving = False
        
        elif after.channel and not after.self_deaf:
            # ボットが新しいチャンネルに参加した、またはスピーカーミュートが解除された場合
            await set_speaker_mute(member.guild, True)
        return

    # 以下は既存のコードをそのま維持
    if before.channel != after.channel:
        if before.channel is not None and bot.user in before.channel.members:
            # ボットがいるチャンネルから誰かが退出した場合
            if len([m for m in before.channel.members if not m.bot]) == 0:
                # ボット以外のメンバーがいなくなった場合
                guild_id = before.channel.guild.id
                if guild_id in voice_state_timers:
                    voice_state_timers[guild_id].cancel()
                voice_state_timers[guild_id] = asyncio.create_task(disconnect_after_timeout(before.channel))
        
        if after.channel is not None and bot.user in after.channel.members:
            # ボットがいるチャンネルに誰かが入室した場合
            guild_id = after.channel.guild.id
            if guild_id in voice_state_timers:
                voice_state_timers[guild_id].cancel()
                del voice_state_timers[guild_id]

async def disconnect_after_timeout(channel):
    await asyncio.sleep(60)  # 1分待機
    if channel.guild.voice_client and len([m for m in channel.members if not m.bot]) == 0:
        await channel.guild.voice_client.disconnect()
        embed = discord.Embed(title="自動切断", description=f"{channel.mention} にユーザーがいなくなったため、切断しました。", color=COLORS['info'])
        
        # 最後にコマンドが実行されたチャンネルにメッセージを送信
        guild_id = channel.guild.id
        if guild_id in last_command_channels:
            await last_command_channels[guild_id].send(embed=embed)
        else:
            # 最後のコマンドチャンネルが不明な場合は、テキストチャンネルを探す
            for text_channel in channel.guild.text_channels:
                if text_channel.permissions_for(channel.guild.me).send_messages:
                    await text_channel.send(embed=embed)
                    break
    
    if channel.guild.id in voice_state_timers:
        del voice_state_timers[channel.guild.id]

@bot.command()
@commands.is_owner()
async def sync(ctx):
    try:
        synced = await bot.tree.sync()
        await ctx.send(f"Synced {len(synced)} command(s)")
    except Exception as e:
        await ctx.send(f"Failed to sync commands: {e}")

@bot.tree.command(name="status", description="ボットのリアルタイムステータスを表示")
async def status(interaction: discord.Interaction):
    view = StatusView(bot)
    embed = create_status_embed(bot)
    await interaction.response.send_message(embed=embed, view=view)
    view.message = await interaction.original_response()
    if not update_status_task.is_running():
        update_status_task.start(view)

@bot.tree.command(name="timeout", description="指定したユーザーをタイムアウトします")
@app_commands.describe(user="タイムアウトするユーザー", duration="タイムアウト期間（分）", reason="タイムアウトの理由")
@app_commands.checks.has_permissions(moderate_members=True)
async def timeout(interaction: discord.Interaction, user: discord.Member, duration: int, reason: str = None):
    if user.top_role >= interaction.user.top_role:
        await interaction.response.send_message("自分と同じか上位の役職のメンバーをタイムアウトすることはできません。", ephemeral=True)
        return

    try:
        await user.timeout(discord.utils.utcnow() + datetime.timedelta(minutes=duration), reason=reason)
        embed = discord.Embed(title="タイムアウト", color=COLORS['warning'])
        embed.add_field(name="対象ユーザー", value=user.mention, inline=False)
        embed.add_field(name="期間", value=f"{duration}分", inline=False)
        embed.add_field(name="理由", value=reason or "理由なし", inline=False)
        await interaction.response.send_message(embed=embed)
    except discord.errors.Forbidden:
        await interaction.response.send_message("タイムアウトする権限がありせん。", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"エラーが発生しました: {e}", ephemeral=True)

@bot.tree.command(name="kick", description="指定したユーザーをキックします")
@app_commands.describe(user="キックするユーザ", reason="キックの理")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, user: discord.Member, reason: str = None):
    if user.top_role >= interaction.user.top_role:
        await interaction.response.send_message("自分と同じか上位の役職のメンバーをキックすることはきせん。", ephemeral=True)
        return

    try:
        await user.kick(reason=reason)
        embed = discord.Embed(title="キック", color=COLORS['error'])
        embed.add_field(name="対象ユーザー", value=user.mention, inline=False)
        embed.add_field(name="理由", value=reason or "理由なし", inline=False)
        await interaction.response.send_message(embed=embed)
    except discord.errors.Forbidden:
        await interaction.response.send_message("キックする権限がありません。", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"エラーが発しました: {e}", ephemeral=True)

@timeout.error
@kick.error
async def command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.errors.MissingPermissions):
        await interaction.response.send_message("このコマンドを実行する権限がありません", ephemeral=True)
    else:
        await interaction.response.send_message(f"エラーが発生ました: {error}", ephemeral=True)

@bot.tree.command(name="userstatus", description="ユーザーのステータスを表示")
async def userstatus(interaction: discord.Interaction, user: discord.Member = None):
    user = user or interaction.user
    embed = discord.Embed(title="ーザステータス", color=COLORS['info'])
    embed.add_field(name="ユーザー名", value=user.name, inline=False)
    embed.add_field(name="ユーザーID", value=user.id, inline=False)
    embed.add_field(name="アカウント作成日", value=user.created_at.strftime("%Y-%m-%d %H:%M:%S"), inline=False)
    embed.add_field(name="サーバー参加日", value=user.joined_at.strftime("%Y-%m-%d %H:%M:%S"), inline=False)
    embed.add_field(name="役職", value=user.top_role.name, inline=False)
    embed.set_thumbnail(url=user.avatar.url if user.avatar else None)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="serverinfo", description="サーバーの情報を表示")
async def serverinfo(interaction: discord.Interaction):
    guild = interaction.guild
    embed = discord.Embed(title=f"{guild.name}", color=COLORS['info'])
    
    # サーバーアイコン
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    
    # 本情報
    owner = guild.owner
    embed.add_field(name="Owner", value=f"{owner.name}", inline=True)
    embed.add_field(name="Members", value=f"{guild.member_count}", inline=True)
    embed.add_field(name="Roles", value=f"{len(guild.roles)}", inline=True)
    
    # チャンネル情報
    categories = len(guild.categories)
    text_channels = len(guild.text_channels)
    voice_channels = len(guild.voice_channels)
    embed.add_field(name="Category Channels", value=f"{categories}", inline=True)
    embed.add_field(name="Text Channels", value=f"{text_channels}", inline=True)
    embed.add_field(name="Voice Channels", value=f"{voice_channels}", inline=True)
    
    # 役職リスト
    role_list = ", ".join([role.name for role in guild.roles if role.name != "@everyone"])
    embed.add_field(name="Role List", value=role_list, inline=False)
    
    # サーバー作成日とID
    created_at = guild.created_at.strftime("%Y/%m/%d %H:%M:%S")
    embed.set_footer(text=f"ID: {guild.id} | Server Created • {created_at}")
    
    await interaction.response.send_message(embed=embed)

# グローバル変数を追加
log_channel_id = None
server_join_log_channel_id = None

def load_log_channels():
    global log_channel_id, server_join_log_channel_id
    try:
        with open('log_channels.json', 'r') as f:
            channels = json.load(f)
            log_channel_id = channels.get('log_channel_id')
            server_join_log_channel_id = channels.get('server_join_log_channel_id')
    except FileNotFoundError:
        pass

def save_log_channels():
    with open('log_channels.json', 'w') as f:
        json.dump({
            'log_channel_id': log_channel_id,
            'server_join_log_channel_id': server_join_log_channel_id
        }, f)

# 起動時にログチャンネルの設定を読み込む
load_log_channels()

# 既存の /setlog コマンドを更新
@bot.tree.command(name="setlog", description="admin only")
async def set_log_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    if str(interaction.user.id) != OWNER_ID:
        await interaction.response.send_message("このコマンドはボットの所有者のみが使用できます。", ephemeral=True)
        return

    global log_channel_id
    log_channel_id = channel.id
    save_log_channels()
    await interaction.response.send_message(f"起動ログの送信先を {channel.mention} に設定しました。", ephemeral=True)

# 新しい /setlog2 コマンドを追加
@bot.tree.command(name="setlog2", description="admin only")
async def set_server_join_log_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    if str(interaction.user.id) != OWNER_ID:
        await interaction.response.send_message("こコマンドはボットの所有者のみが使用できます。", ephemeral=True)
        return

    global server_join_log_channel_id
    server_join_log_channel_id = channel.id
    save_log_channels()
    await interaction.response.send_message(f"サーバー参加通知の送信先を {channel.mention} に設定しました。", ephemeral=True)

# on_guild_join イベントハンドラを更新
@bot.event
async def on_guild_join(guild):
    # サーバーの最初のテキストチャンネルを探す
    channel = next((ch for ch in guild.text_channels if ch.permissions_for(guild.me).send_messages), None)
    
    if channel:
        embed = discord.Embed(title=f"Ray Music へようこそ！", color=COLORS['success'])
        embed.description = (
            f"こんにちは、{guild.name} の皆さん！Ray Music をお選びいただきありがとうございます。\n"
            "音楽を楽しむお手伝いをさせていただきます。"
        )
        embed.add_field(name="主な機能", value=(
            "• 音楽の再生\n"
            "• プレイリスト管理\n"
            "• サーバー情報の表示\n"
            "• モデレーション機能"
        ), inline=False)
        embed.add_field(name="使い方", value=(
            "1. ボイスチャンネルに参加します\n"
            "2. `!play <URL or 検索語句>` で音楽を再生\n"
            "3. `!help` でより詳細なコマンド一覧を確認"
        ), inline=False)
        embed.add_field(name="サポート", value=(
            "問題や質問がある場合は、`/help` コマンドを使用するか、"
            "開発者にお問い合わせください。"
        ), inline=False)
        embed.set_footer(text=f"バージョン: {BOT_VERSION}")
        
        await channel.send(embed=embed)
    
    # サーバー参加通知用のログチャンネルに通知を送信
    if server_join_log_channel_id:
        log_channel = bot.get_channel(server_join_log_channel_id)
        if log_channel:
            log_embed = discord.Embed(title="新しいサーバーに参加", color=COLORS['info'])
            log_embed.add_field(name="サーバー名", value=guild.name, inline=True)
            log_embed.add_field(name="サーバーID", value=guild.id, inline=True)
            log_embed.add_field(name="オーナー", value=f"{guild.owner} ({guild.owner.id})", inline=True)
            log_embed.add_field(name="メンバー数", value=guild.member_count, inline=True)
            await log_channel.send(embed=log_embed)

# エラーハンドラも更新
@set_log_channel.error
@set_server_join_log_channel.error
async def log_channel_error(interaction: discord.Interaction, error):
    await interaction.response.send_message(f"エラーが発生しました: {error}", ephemeral=True)

bot.run(TOKEN)

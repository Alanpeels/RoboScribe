# bot.py
import os
import sys
import asyncio
import shutil
import json
import tempfile
import logging
import discord

# Configure logging directly using Python's logging module
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s:%(name)s: %(message)s"
)

from dotenv import load_dotenv

# ───────────────── tiny web server (keep Fly machine alive) ───────────────
from aiohttp import web

async def _health(_):
    return web.Response(text="ok")

async def start_web_server():
    app = web.Application()
    app.add_routes([web.get("/", _health), web.get("/health", _health)])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    print("[web] HTTP server listening on 0.0.0.0:8080")

# ─────────────────────────── ENV ───────────────────────────
load_dotenv()  # (won't override Fly secrets; fine for local)
TOKEN = os.getenv("DISCORD_TOKEN")

# ───────────────────────── INTENTS ─────────────────────────
intents = discord.Intents.default()
intents.guilds = True
intents.voice_states = True
intents.message_content = True  # make sure this is enabled in the Dev Portal

# ─────────────────────────  BOT  ──────────────────────────
bot = discord.Bot(intents=intents)

# { guild_id: {"sink": sink, "channel": text_channel} }
recording_states: dict[int, dict] = {}

# ─────────────── Interaction helper (single reply) ──────────
async def send_reply(ctx: discord.ApplicationContext, *args, **kwargs):
    """
    Always ensure the interaction is acknowledged and then use followups.
    This avoids 'Unknown interaction' and duplicate messages.
    """
    try:
        if not (getattr(ctx, "deferred", False) or getattr(ctx, "responded", False)):
            await ctx.defer(ephemeral=kwargs.pop("ephemeral", False))
    except Exception:
        pass
    return await ctx.followup.send(*args, **kwargs)

# ───────────── Runtime diagnostics / opus / ffmpeg ────────
def try_load_opus() -> tuple[bool, str]:
    """Load libopus (required for voice)."""
    import discord.opus as opus
    if opus.is_loaded():
        return True, "Opus: ✅ already loaded"

    explicit = os.getenv("OPUS_DLL_PATH")
    tried = []
    if explicit:
        try:
            opus.load_opus(explicit)
            if opus.is_loaded():
                return True, f"Opus: ✅ loaded ({explicit})"
        except Exception:
            tried.append(explicit)

    candidates = []
    if sys.platform.startswith("win"):
        candidates = ["libopus-0.dll", "opus.dll", "libopus.dll", "opus"]
    elif sys.platform == "darwin":
        candidates = ["libopus.dylib", "opus"]
    else:
        candidates = ["libopus.so.0", "libopus.so", "opus"]

    for name in candidates:
        try:
            opus.load_opus(name)
            if opus.is_loaded():
                return True, f"Opus: ✅ loaded ({name})"
        except Exception:
            tried.append(name)
            continue

    return False, "Opus: ❌ not loaded (tried: " + ", ".join(tried or ["<none>"]) + ")"

def voice_runtime_ok() -> tuple[bool, str]:
    """Check PyNaCl, opus, ffmpeg, SpeechRecognition, pydub."""
    try:
        import nacl  # type: ignore
        have_nacl = True
    except Exception:
        have_nacl = False

    opus_ok, opus_msg = try_load_opus()
    ffmpeg_path = shutil.which("ffmpeg")

    try:
        import speech_recognition
        sr_msg = "✅ available"
    except Exception:
        sr_msg = "❌ missing"

    try:
        import pydub
        pydub_msg = "✅ available"
    except Exception:
        pydub_msg = "❌ missing"

    parts = []
    parts.append("PyNaCl: " + ("✅ present" if have_nacl else "❌ missing"))
    parts.append(opus_msg)
    parts.append("ffmpeg: " + (f"✅ {ffmpeg_path}" if ffmpeg_path else "⚠️ not found (we'll use WAV)"))
    parts.append(f"SpeechRecognition: {sr_msg}")
    parts.append(f"Pydub: {pydub_msg}")
    msg = " | ".join(parts)

    return (have_nacl and opus_ok), msg

def choose_sink_cls():
    """
    Prefer MP3 if both ffmpeg and pydub are available; otherwise fall back to WAV.
    """
    import discord.sinks
    have_ffmpeg = shutil.which("ffmpeg") is not None
    try:
        import pydub  # noqa
        have_pydub = True
    except ImportError:
        have_pydub = False

    return discord.sinks.MP3Sink if (have_ffmpeg and have_pydub) else discord.sinks.WaveSink

# ───────────────── Transcription and AI (free) ────────────
async def transcribe_audio_free(audio_file_path: str) -> str:
    """Google Speech Recognition (free). Input must be WAV."""
    import speech_recognition as sr
    if not audio_file_path.endswith(".wav"):
        raise Exception(f"transcribe_audio_free only accepts WAV; got: {audio_file_path}")

    r = sr.Recognizer()
    with sr.AudioFile(audio_file_path) as source:
        audio = r.record(source)
    return r.recognize_google(audio)

def extract_key_sentences(text: str, num_sentences: int = 3) -> list:
    import re
    from collections import Counter
    sentences = re.split(r'[.!?]+', text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 10]
    if len(sentences) <= num_sentences:
        return sentences
    words = re.findall(r'\w+', text.lower())
    word_freq = Counter(words)
    scores = {}
    for i, s in enumerate(sentences):
        s_words = re.findall(r'\w+', s.lower())
        scores[i] = sum(word_freq[w] for w in s_words)
    top = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)[:num_sentences]
    top.sort()
    return [sentences[i] for i in top]

async def generate_notes_from_transcription_free(transcription: str) -> str:
    import re
    from collections import Counter
    lines = transcription.split('\n')
    paragraphs = [line.strip() for line in lines if line.strip()]
    full_text = ' '.join(paragraphs)

    key_sentences = extract_key_sentences(full_text, 5)
    words = re.findall(r'\b[a-zA-Z]{4,}\b', full_text.lower())
    common_words = set(['this','that','with','have','will','been','from','they','know','want','good','much',
                        'some','time','very','when','come','here','just','like','long','make','many',
                        'over','such','take','than','them','well','were'])
    filtered = [w for w in words if w not in common_words]
    word_freq = Counter(filtered)
    keywords = [w for w, _ in word_freq.most_common(10)]

    action_words = ['will','should','need','must','have to','going to']
    action_items = []
    for sentence in transcription.split('.'):
        s = sentence.strip()
        if any(a in s.lower() for a in action_words) and 10 < len(s) < 200:
            action_items.append(s + '.')

    out = []
    out.append("# 📝 Call Notes \n")
    out.append("## 📋 Summary\n")
    out.append(f"This call covered various topics with {len(paragraphs)} main discussion points.\n\n")
    if key_sentences:
        out.append("## 🔑 Key Points\n")
        out += [f"• {s}\n" for s in key_sentences[:5]]
        out.append("\n")
    if action_items:
        out.append("## ✅ Potential Action Items\n")
        out += [f"• {a}\n" for a in action_items[:5]]
        out.append("\n")
    if keywords:
        out.append("## 🏷️ Key Topics\n")
        out += [f"• {k.title()}\n" for k in keywords[:8]]
        out.append("\n")
    out.append("## 📄 Full Transcription\n")
    out.append("```\n")
    out.append(transcription)
    out.append("\n```\n")
    return "".join(out)

# ───────────────────────── Events ─────────────────────────
@bot.event
async def on_ready():
    print(f"{bot.user} has connected to Discord!")
    ok, diag = voice_runtime_ok()
    print("Voice Runtime →", diag)
    print("🚀 Discord Bot with FREE transcription and AI features is ready!")
    print("ℹ️ Using Google Speech Recognition (free) + custom summarization")

# ─────────────────────── Slash Commands ───────────────────
@bot.slash_command(name="join", description="Join your current voice channel")
@discord.default_permissions(manage_guild=True)
async def join(ctx: discord.ApplicationContext):
    if not ctx.author.voice or not ctx.author.voice.channel:
        return await send_reply(ctx, "❌ You need to be in a voice channel!")

    channel = ctx.author.voice.channel

    async def _connect_once():
        if ctx.voice_client is None or not ctx.voice_client.is_connected():
            await channel.connect(timeout=20, reconnect=False)
        elif ctx.voice_client.channel != channel:
            await ctx.voice_client.move_to(channel)

    try:
        await _connect_once()
        print(f"[voice] Connected to {channel.name} (guild={ctx.guild.name})")
        return await send_reply(ctx, f"✅ Connected to **{channel.name}**")
    except Exception as e:
        # Retry one time for fresh gateway hiccup (4006)
        if "4006" in str(e) or "Invalid session" in str(e):
            await asyncio.sleep(2)
            await bot.wait_until_ready()
            try:
                await _connect_once()
                return await send_reply(ctx, f"✅ Connected to **{channel.name}** (after retry)")
            except Exception as e2:
                print(f"[voice-error] Retry failed: {e2!r}")
                return await send_reply(ctx, f"❌ Failed to connect after retry: `{e2}`")
        print(f"[voice-error] Could not connect: {e!r}")
        return await send_reply(ctx, f"❌ Failed to connect: `{e}`")

@bot.slash_command(name="leave", description="Leave the voice channel")
@discord.default_permissions(manage_guild=True)
async def leave(ctx: discord.ApplicationContext):
    if ctx.voice_client is None:
        return await send_reply(ctx, "❌ I'm not connected to a voice channel.")
    gid = ctx.guild.id
    if gid in recording_states:
        try:
            ctx.voice_client.stop_recording()
        except Exception:
            pass
        recording_states.pop(gid, None)
    await ctx.voice_client.disconnect()
    await send_reply(ctx, "✅ Disconnected from voice.")

@bot.slash_command(name="record_start", description="Start recording the voice channel")
@discord.default_permissions(manage_guild=True)
async def record_start(ctx: discord.ApplicationContext):
    if ctx.voice_client is None or not ctx.voice_client.is_connected():
        return await send_reply(ctx, "❌ I'm not connected to a voice channel. Use `/join` first.")

    gid = ctx.guild.id
    if gid in recording_states:
        return await send_reply(ctx, "❌ Already recording! Use `/record_stop` first.")

    try:
        sink_cls = choose_sink_cls()
        sink = sink_cls()

        def finished_callback(sink, channel, *args):
            asyncio.run_coroutine_threadsafe(process_recording(sink, channel), bot.loop)

        ctx.voice_client.start_recording(sink, finished_callback, ctx.channel)
        recording_states[gid] = {"sink": sink, "channel": ctx.channel}

        fmt = "MP3" if sink_cls.__name__.upper().startswith("MP3") else "WAV"
        embed = discord.Embed(
            title="🔴 Recording Started",
            description=(
                "**NOTICE**: This voice channel is now being recorded.\n\n"
                "Use `/record_stop` to stop recording and generate transcription + notes."
            ),
            color=discord.Color.red()
        )
        embed.set_footer(text=f"Recording format: {fmt} | Using free transcription")
        await send_reply(ctx, embed=embed)
    except Exception as e:
        recording_states.pop(gid, None)
        await send_reply(ctx, f"❌ Failed to start recording: {e}")

@bot.slash_command(name="record_stop", description="Stop recording and generate transcription with AI notes")
@discord.default_permissions(manage_guild=True)
async def record_stop(ctx: discord.ApplicationContext):
    gid = ctx.guild.id
    if gid not in recording_states:
        return await send_reply(ctx, "❌ No recording is currently running.")
    if ctx.voice_client is None or not ctx.voice_client.is_connected():
        recording_states.pop(gid, None)
        return await send_reply(ctx, "❌ I'm not connected to a voice channel.")

    try:
        ctx.voice_client.stop_recording()  # triggers finished_callback
        recording_states.pop(gid, None)
        await send_reply(ctx, "⏹️ Recording stopped. Processing audio… I'll post the transcript & notes here.")
    except Exception as e:
        recording_states.pop(gid, None)
        await send_reply(ctx, f"❌ Failed to stop recording: {e}")

@bot.slash_command(name="status", description="Check bot connection/recording status")
async def status(ctx: discord.ApplicationContext):
    embed = discord.Embed(title="🤖 Bot Status", color=discord.Color.blurple())
    vc = ctx.voice_client
    if vc and vc.is_connected():
        embed.add_field(name="Voice Connection", value=f"✅ Connected to **{vc.channel.name}**", inline=False)
    else:
        embed.add_field(name="Voice Connection", value="❌ Not connected", inline=False)
    rec = "🔴 Active" if ctx.guild.id in recording_states else "⚪ Inactive"
    embed.add_field(name="Recording", value=rec, inline=False)
    embed.add_field(name="AI Features", value="✅ Free tools ready", inline=False)
    if ctx.author.voice and ctx.author.voice.channel:
        embed.add_field(name="Your Voice Channel", value=ctx.author.voice.channel.name, inline=False)
    else:
        embed.add_field(name="Your Voice Channel", value="❌ Not in voice", inline=False)
    await ctx.respond(embed=embed)

@bot.slash_command(name="debug", description="Show voice environment diagnostics")
async def debug(ctx: discord.ApplicationContext):
    ok, msg = voice_runtime_ok()
    color = discord.Color.green() if ok else discord.Color.orange()
    emb = discord.Embed(title="🎧 Voice Diagnostics", description=msg, color=color)
    await ctx.respond(embed=emb)

@bot.slash_command(name="help_bot", description="Show available commands")
async def help_bot(ctx: discord.ApplicationContext):
    embed = discord.Embed(title="🤖 Discord Voice Bot Commands", color=discord.Color.blue())
    embed.add_field(name="/join", value="Join your voice channel", inline=False)
    embed.add_field(name="/leave", value="Leave the voice channel", inline=False)
    embed.add_field(name="/record_start", value="Start recording the voice channel", inline=False)
    embed.add_field(name="/record_stop", value="Stop recording and generate transcription + notes", inline=False)
    embed.add_field(name="/status", value="Check bot status", inline=False)
    embed.add_field(name="/debug", value="Show voice diagnostics", inline=False)
    embed.add_field(name="/help_bot", value="Show this help message", inline=False)
    embed.set_footer(text="🆓 Using completely FREE transcription and AI tools!")
    await ctx.respond(embed=embed)

# ──────────── Recording Processing Function ────────────
async def process_recording(sink, channel: discord.TextChannel):
    made_files = []
    all_transcriptions = []

    try:
        if not sink.audio_data:
            await channel.send("❌ No audio captured (no one spoke).")
            return

        guild_id = channel.guild.id

        # Determine format
        is_mp3 = False
        try:
            if hasattr(sink, "encoding") and str(sink.encoding).lower() == "mp3":
                is_mp3 = True
            elif "MP3" in sink.__class__.__name__:
                is_mp3 = True
        except Exception:
            pass

        for user_id, audio in sink.audio_data.items():
            ext = "mp3" if is_mp3 else "wav"
            filename = f"recording_{guild_id}_{user_id}.{ext}"
            try:
                with open(filename, "wb") as f:
                    f.write(audio.file.getvalue())
                made_files.append(filename)

                if os.path.getsize(filename) > 0:
                    wav_filename = None
                    if filename.endswith(".mp3"):
                        try:
                            from pydub import AudioSegment
                            wav_filename = filename.replace(".mp3", ".wav")
                            AudioSegment.from_mp3(filename).export(wav_filename, format="wav")
                            made_files.append(wav_filename)
                            print(f"[info] Converted {filename} → {wav_filename}")
                        except Exception as e:
                            print(f"[error] MP3→WAV failed for {filename}: {e}")
                            await channel.send(f"⚠️ Could not convert MP3 from user {user_id} to WAV. Skipping.")
                            continue
                    else:
                        wav_filename = filename

                    if wav_filename and os.path.exists(wav_filename):
                        try:
                            transcription = await transcribe_audio_free(wav_filename)
                            if transcription.strip():
                                all_transcriptions.append(transcription)
                                print(f"[info] Transcribed {wav_filename}")
                        except Exception as e:
                            print(f"[error] Transcription failed for {wav_filename}: {e}")
                            await channel.send(f"⚠️ Transcription failed for user {user_id}: {e}")
                else:
                    print(f"[warn] Empty file produced: {filename}")
            except Exception as e:
                print(f"[error] Could not write {filename}: {e}")

        if not all_transcriptions:
            await channel.send("❌ No speech detected in the recording.")
            return

        full_transcription = "\n".join(all_transcriptions)
        ai_notes = await generate_notes_from_transcription_free(full_transcription)

        # Preview embed
        preview = full_transcription[:1000] + ("..." if len(full_transcription) > 1000 else "")
        embed = discord.Embed(
            title="📝 Recording Processed ",
            description="Transcription and notes generated using free services.",
            color=discord.Color.green(),
        )
        embed.add_field(name="🎤 Transcription Preview", value=f"```{preview}```", inline=False)
        await channel.send(embed=embed)

        # Attach full transcript if long
        if len(full_transcription) > 1000:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
                f.write(full_transcription)
                path = f.name
            await channel.send("📄 Full transcription:", file=discord.File(path, "transcription.txt"))
            os.unlink(path)

        # Attach notes
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(ai_notes)
            notes_path = f.name
        await channel.send("🤖 AI-Generated Notes :", file=discord.File(notes_path, "ai_notes.md"))
        os.unlink(notes_path)

    except Exception as e:
        await channel.send(f"❌ Error processing recording: {e}")
    finally:
        for p in made_files:
            try:
                os.remove(p)
            except Exception as rm_err:
                print(f"[warn] Could not remove {p}: {rm_err}")

# ─────────────────────── Entry Point ──────────────────────
if __name__ == "__main__":
    if not TOKEN:
        print("❌ DISCORD_TOKEN not found in env/secrets.")
        raise SystemExit(1)

    masked = (TOKEN[:8] + "..." + TOKEN[-6:]) if len(TOKEN) > 20 else TOKEN
    print(f"Using DISCORD_TOKEN (masked): {masked!r} length={len(TOKEN)}")
    print("🚀 Starting Discord Bot with FREE transcription and AI features!")
    print("ℹ️ Using Google Speech Recognition (free) + custom summarization")

    # start the tiny web server to keep the Fly machine "healthy"
    bot.loop.create_task(start_web_server())

    # IMPORTANT: run() blocks forever and auto-reconnects
    bot.run(TOKEN)
import os
import discord
from discord import app_commands
from discord.ext import voice_recv
from dotenv import load_dotenv
import speech_recognition as sr
import google.generativeai as genai
from database import Database
from audio_sink import WavAudioSink
from flask import Flask
import threading
import bot  # Assuming your main bot code is in bot.py


# Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

# Configure Gemini API
genai.configure(api_key=GEMINI_API_KEY)

# Initialize bot
intents = discord.Intents.default()
intents.voice_states = True
intents.guilds = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
db = Database()

# Storage for active recordings
active_recordings = {}

@client.event
async def on_ready():
    await tree.sync()
    print(f'Bot logged in as {client.user}')

@tree.command(name="start_recording", description="Start recording voice channel")
async def start_recording(interaction: discord.Interaction):
    if not interaction.user.voice:
        embed = discord.Embed(
            title="❌ Error",
            description="You must be in a voice channel to start recording!",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    channel = interaction.user.voice.channel
    
    if interaction.guild.id in active_recordings:
        embed = discord.Embed(
            title="⚠️ Already Recording",
            description="A recording is already in progress in this server!",
            color=discord.Color.orange()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    # Connect to voice channel
    voice_client = await channel.connect(cls=voice_recv.VoiceRecvClient)
    
    # Get participant IDs
    participant_ids = [member.id for member in channel.members if not member.bot]
    
    # Create audio sink and start recording
    filename = f'recording_{interaction.guild.id}.wav'
    sink = WavAudioSink(filename)
    voice_client.listen(sink)
    
    # Store recording info
    active_recordings[interaction.guild.id] = {
        'voice_client': voice_client,
        'sink': sink,
        'filename': filename,
        'participants': participant_ids
    }
    
    embed = discord.Embed(
        title="🎙️ Recording Started",
        description=f"Now recording in **{channel.name}**",
        color=discord.Color.green()
    )
    embed.add_field(name="Participants", value=f"{len(participant_ids)} member(s)", inline=True)
    embed.add_field(name="Status", value="🔴 Live", inline=True)
    embed.set_footer(text="Use /stop_recording to finish")
    
    await interaction.response.send_message(embed=embed)

@tree.command(name="stop_recording", description="Stop recording and process")
@app_commands.describe(name="Name for this transcript")
async def stop_recording(interaction: discord.Interaction, name: str):
    if interaction.guild.id not in active_recordings:
        embed = discord.Embed(
            title="❌ No Active Recording",
            description="There's no recording in progress!",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    # Send initial processing message
    embed = discord.Embed(
        title="⏳ Processing Recording",
        description="Stopping recording and processing audio...",
        color=discord.Color.blue()
    )
    await interaction.response.send_message(embed=embed)
    
    recording = active_recordings[interaction.guild.id]
    voice_client = recording['voice_client']
    filename = recording['filename']
    participants = recording['participants']
    
    # Stop recording
    voice_client.stop_listening()
    await voice_client.disconnect()
    
    del active_recordings[interaction.guild.id]
    
    # Transcribe audio
    try:
        recognizer = sr.Recognizer()
        with sr.AudioFile(filename) as source:
            audio = recognizer.record(source)
            transcript_text = recognizer.recognize_google(audio)
    except sr.UnknownValueError:
        embed = discord.Embed(
            title="❌ Transcription Failed",
            description="Could not understand the audio. Please ensure:\n• Clear speech\n• Minimal background noise\n• Audio is not too long",
            color=discord.Color.red()
        )
        await interaction.edit_original_response(embed=embed)
        os.remove(filename)
        return
    except sr.RequestError as e:
        embed = discord.Embed(
            title="❌ Service Error",
            description=f"Transcription service error: {e}",
            color=discord.Color.red()
        )
        await interaction.edit_original_response(embed=embed)
        os.remove(filename)
        return
    
    # Generate AI summary
    try:
        model = genai.GenerativeModel('gemini-2.0-flash')
        prompt = f"Summarize the following transcript with key points:\n\n{transcript_text}"
        response = model.generate_content(prompt)
        summary = response.text
    except Exception as e:
        summary = f"Could not generate summary: {e}"
    
    # Save to database
    transcript_id = db.save_transcript(name, transcript_text, summary, participants)
    
    # Cleanup audio file
    os.remove(filename)
    
    # Send success message
    embed = discord.Embed(
        title="✅ Transcript Saved",
        description=f"Recording **'{name}'** has been processed and saved!",
        color=discord.Color.green()
    )
    embed.add_field(name="Transcript ID", value=f"`{transcript_id}`", inline=True)
    embed.add_field(name="Participants", value=f"{len(participants)} member(s)", inline=True)
    embed.add_field(name="Preview", value=transcript_text[:100] + "..." if len(transcript_text) > 100 else transcript_text, inline=False)
    embed.set_footer(text=f"Use /view_id {transcript_id} to see the full transcript")
    
    await interaction.edit_original_response(embed=embed)

@tree.command(name="transcript", description="Search for transcripts")
@app_commands.describe(search_term="Search term to find transcripts")
async def transcript(interaction: discord.Interaction, search_term: str):
    results = db.search_transcripts(search_term)
    
    if not results:
        embed = discord.Embed(
            title="🔍 No Results",
            description=f"No transcripts found matching **'{search_term}'**",
            color=discord.Color.orange()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    embed = discord.Embed(
        title="📝 Search Results",
        description=f"Found {len(results)} transcript(s) matching **'{search_term}'**",
        color=discord.Color.blue()
    )
    
    for idx, (transcript_id, name, date) in enumerate(results[:10], 1):  # Limit to 10 results
        date_formatted = date[:10] if len(date) >= 10 else date
        embed.add_field(
            name=f"{idx}. {name}",
            value=f"ID: `{transcript_id}` • Date: {date_formatted}",
            inline=False
        )
    
    if len(results) > 10:
        embed.set_footer(text=f"Showing 10 of {len(results)} results")
    else:
        embed.set_footer(text="Use /view_id [ID] to view a transcript")
    
    await interaction.response.send_message(embed=embed)

@tree.command(name="view_id", description="View a transcript by ID")
@app_commands.describe(transcript_id="ID of the transcript")
async def view_id(interaction: discord.Interaction, transcript_id: int):
    result = db.get_transcript(transcript_id)
    
    if not result:
        embed = discord.Embed(
            title="❌ Not Found",
            description=f"No transcript found with ID `{transcript_id}`",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    name, text, summary, date = result
    date_formatted = date[:10] if len(date) >= 10 else date
    
    embed = discord.Embed(
        title=f"📄 {name}",
        color=discord.Color.blue()
    )
    embed.add_field(name="📅 Date", value=date_formatted, inline=True)
    embed.add_field(name="🆔 ID", value=f"`{transcript_id}`", inline=True)
    
    # Truncate text if too long (Discord has 1024 char limit per field)
    transcript_display = text[:1000] + "..." if len(text) > 1000 else text
    summary_display = summary[:1000] + "..." if len(summary) > 1000 else summary
    
    embed.add_field(name="📝 Transcript", value=transcript_display or "No transcript available", inline=False)
    embed.add_field(name="✨ AI Summary", value=summary_display or "No summary available", inline=False)
    
    if len(text) > 1000 or len(summary) > 1000:
        embed.set_footer(text="⚠️ Content truncated due to length")
    
    await interaction.response.send_message(embed=embed)

client.run(DISCORD_TOKEN)



app = Flask(__name__)

@app.route("/")
def home():
    return "RoboScribe Bot is running", 200

if __name__ == "__main__":
    # Run the bot in a separate thread so Flask can run in main thread
    threading.Thread(target=lambda: bot.main()).start()

    # Run Flask server on 0.0.0.0:8080 to listen on all interfaces
    app.run(host="0.0.0.0", port=8080)

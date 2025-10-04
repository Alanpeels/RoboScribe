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
from pydub import AudioSegment
from pydub.silence import split_on_silence

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
    await interaction.response.defer()
    
    if not interaction.user.voice:
        embed = discord.Embed(
            title="❌ Error",
            description="You must be in a voice channel to start recording!",
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    
    channel = interaction.user.voice.channel
    
    if interaction.guild.id in active_recordings:
        embed = discord.Embed(
            title="⚠️ Already Recording",
            description="A recording is already in progress in this server!",
            color=discord.Color.orange()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    
    try:
        voice_client = await channel.connect(cls=voice_recv.VoiceRecvClient)
        participant_ids = [member.id for member in channel.members if not member.bot]
        filename = f'recording_{interaction.guild.id}.wav'
        sink = WavAudioSink(filename)
        voice_client.listen(sink)
        
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
        await interaction.followup.send(embed=embed)
    except Exception as e:
        embed = discord.Embed(
            title="❌ Connection Error",
            description=f"Failed to start recording: {str(e)}",
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

def transcribe_audio_chunks(filename):
    """Transcribe audio file, using chunking only if necessary"""
    try:
        # Check audio duration first
        audio = AudioSegment.from_wav(filename)
        duration_seconds = len(audio) / 1000  # Convert ms to seconds
        
        recognizer = sr.Recognizer()
        
        # If audio is under 50 seconds, transcribe directly without chunking
        if duration_seconds <= 50:
            try:
                with sr.AudioFile(filename) as source:
                    audio_data = recognizer.record(source)
                    text = recognizer.recognize_google(audio_data)
                    return text
            except sr.UnknownValueError:
                return None
            except Exception as e:
                print(f"Error in direct transcription: {e}")
                return None
        
        # For longer audio, use chunking
        chunk_length_ms = 50000  # 50 seconds
        chunks = []
        
        for i in range(0, len(audio), chunk_length_ms):
            chunk = audio[i:i + chunk_length_ms]
            chunks.append(chunk)
        
        # Transcribe each chunk
        full_transcript = []
        
        for idx, chunk in enumerate(chunks):
            chunk_filename = f"temp_chunk_{idx}.wav"
            chunk.export(chunk_filename, format="wav")
            
            try:
                with sr.AudioFile(chunk_filename) as source:
                    audio_data = recognizer.record(source)
                    text = recognizer.recognize_google(audio_data)
                    if text:
                        full_transcript.append(text)
            except sr.UnknownValueError:
                pass
            except Exception as e:
                print(f"Error transcribing chunk {idx}: {e}")
            finally:
                if os.path.exists(chunk_filename):
                    os.remove(chunk_filename)
        
        if not full_transcript:
            return None
        
        return " ".join(full_transcript)
        
    except Exception as e:
        print(f"Error in transcription: {e}")
        return None


@tree.command(name="stop_recording", description="Stop recording and process")
@app_commands.describe(name="Name for this transcript")
async def stop_recording(interaction: discord.Interaction, name: str):
    await interaction.response.defer()
    
    if interaction.guild.id not in active_recordings:
        embed = discord.Embed(
            title="❌ No Active Recording",
            description="There's no recording in progress!",
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    
    embed = discord.Embed(
        title="⏳ Processing Recording",
        description="Stopping recording and processing audio...",
        color=discord.Color.blue()
    )
    await interaction.followup.send(embed=embed)
    
    recording = active_recordings[interaction.guild.id]
    voice_client = recording['voice_client']
    filename = recording['filename']
    participants = recording['participants']
    
    try:
        voice_client.stop_listening()
        await voice_client.disconnect()
        del active_recordings[interaction.guild.id]
    except Exception as e:
        embed = discord.Embed(
            title="❌ Error Stopping Recording",
            description=f"Failed to stop recording properly: {str(e)}",
            color=discord.Color.red()
        )
        await interaction.edit_original_response(embed=embed)
        return
    
    try:
        file_size = os.path.getsize(filename)
        
        if file_size < 1024:
            embed = discord.Embed(
                title="🔇 No Audio Detected",
                description="The recording contains no speech or is too short. Please try again.",
                color=discord.Color.orange()
            )
            await interaction.edit_original_response(embed=embed)
            os.remove(filename)
            return
    except FileNotFoundError:
        embed = discord.Embed(
            title="❌ Recording Error",
            description="Audio file was not created. Please try again.",
            color=discord.Color.red()
        )
        await interaction.edit_original_response(embed=embed)
        return
    
    # Update status message
    embed = discord.Embed(
        title="⏳ Transcribing Audio",
        description="Processing audio chunks... This may take a moment for longer recordings.",
        color=discord.Color.blue()
    )
    await interaction.edit_original_response(embed=embed)
    
    # Transcribe using chunking
    transcript_text = transcribe_audio_chunks(filename)
    
    if not transcript_text:
        embed = discord.Embed(
            title="🔇 No Speech Detected",
            description="Could not detect any speech in the recording. Please ensure clear speech with minimal background noise.",
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
    
    # Cleanup
    if os.path.exists(filename):
        os.remove(filename)
    
    # Success message
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
    await interaction.response.defer()
    
    results = db.search_transcripts(search_term)
    
    if not results:
        embed = discord.Embed(
            title="🔍 No Results",
            description=f"No transcripts found matching **'{search_term}'**",
            color=discord.Color.orange()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    
    embed = discord.Embed(
        title="📝 Search Results",
        description=f"Found {len(results)} transcript(s) matching **'{search_term}'**",
        color=discord.Color.blue()
    )
    
    for idx, (transcript_id, name, date) in enumerate(results[:10], 1):
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
    
    await interaction.followup.send(embed=embed)

@tree.command(name="view_id", description="View a transcript by ID")
@app_commands.describe(transcript_id="ID of the transcript")
async def view_id(interaction: discord.Interaction, transcript_id: int):
    await interaction.response.defer()
    
    result = db.get_transcript(transcript_id)
    
    if not result:
        embed = discord.Embed(
            title="❌ Not Found",
            description=f"No transcript found with ID `{transcript_id}`",
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    
    name, text, summary, date = result
    date_formatted = date[:10] if len(date) >= 10 else date
    
    embed = discord.Embed(
        title=f"📄 {name}",
        color=discord.Color.blue()
    )
    embed.add_field(name="📅 Date", value=date_formatted, inline=True)
    embed.add_field(name="🆔 ID", value=f"`{transcript_id}`", inline=True)
    
    transcript_display = text[:1000] + "..." if len(text) > 1000 else text
    summary_display = summary[:1000] + "..." if len(summary) > 1000 else summary
    
    embed.add_field(name="📝 Transcript", value=transcript_display or "No transcript available", inline=False)
    embed.add_field(name="✨ AI Summary", value=summary_display or "No summary available", inline=False)
    
    if len(text) > 1000 or len(summary) > 1000:
        embed.set_footer(text="⚠️ Content truncated due to length")
    
    # THIS LINE WAS MISSING OR BROKEN
    await interaction.followup.send(embed=embed)


# Flask setup
app = Flask(__name__)

@app.route("/")
def home():
    return "RoboScribe Bot is running", 200

@app.route("/health")
def health():
    return {"status": "healthy", "bot": "online"}, 200

def run_bot():
    """Function to run the Discord bot"""
    client.run(DISCORD_TOKEN)

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    app.run(host="0.0.0.0", port=8080)

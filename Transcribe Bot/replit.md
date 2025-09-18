# Discord Voice Transcription Bot

## Overview
A Discord bot that joins voice channels, records conversations, transcribes audio using FREE Google Speech Recognition, and generates structured notes using custom NLP techniques. No paid API keys required!

## Features
- 🎤 Join and record Discord voice channels
- 📝 Automatic transcription using FREE Google Speech Recognition
- 🤖 AI-powered note generation using custom NLP (completely free)
- 🔄 Real-time recording status and diagnostics
- 📋 Export transcriptions and notes as files
- 🛡️ Proper consent notifications and privacy handling

## Recent Changes
- **2025-09-18**: Initial setup with complete voice recording and AI transcription functionality
- Added FREE transcription using Google Speech Recognition and custom NLP note generation
- Implemented comprehensive slash commands for recording control
- Added proper error handling and runtime diagnostics

## Architecture
- **Bot Framework**: py-cord (discord.py fork with voice recording support)
- **Audio Processing**: FFmpeg for audio encoding/decoding
- **Voice Crypto**: PyNaCl for Discord voice encryption
- **Transcription**: Google Speech Recognition (free tier)
- **AI Notes**: Custom NLP with keyword extraction and action item detection
- **File Handling**: Temporary audio files with automatic cleanup

## Project Structure
```
├── bot.py              # Main bot application
├── .env.example        # Environment variables template
└── replit.md          # Project documentation
```

## Slash Commands
- `/join` - Join your current voice channel
- `/leave` - Leave the voice channel
- `/record_start` - Start recording the voice channel
- `/record_stop` - Stop recording and generate transcription + AI notes
- `/transcribe_last` - Process the last recording with AI
- `/status` - Check bot connection and recording status
- `/debug_voice` - Show voice runtime diagnostics
- `/debug_channel` - Show voice channel permissions
- `/voice_stats` - Show raw voice client statistics
- `/force_reconnect` - Force reconnect to voice channel

## Setup Requirements
1. **Discord Bot Token**: Create a bot at https://discord.com/developers/applications
2. **Bot Permissions**: Voice channel access (Connect, Speak, Use Voice Activity)
3. **Internet Connection**: For Google's free speech recognition service

**No paid API keys required!** Everything runs on free services and local processing.

## User Preferences
- Uses structured AI notes with summaries, key points, action items, and decisions
- Automatic file cleanup after processing
- Consent notifications for recording participants
- JSON-formatted AI output for consistent note structure
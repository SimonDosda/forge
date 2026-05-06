# 🌱 Garden Assistant Bot

A personal AI-powered Telegram bot that remembers everything about your garden and tells you what to do each day based on real-time weather data.

-----

## What It Does

- **Daily briefing** — Every morning, the bot sends you a personalized task list based on the weather forecast and your garden history
- **Persistent memory** — Every action you log (watering, pruning, planting, fertilizing…) is saved to Notion
- **Smart recommendations** — Mistral AI cross-references your garden history with today’s weather to suggest the right tasks at the right time
- **Natural conversation** — Just tell the bot what you did, in plain French or English, and it handles the rest

-----

## Example Interaction

**Morning briefing (automatic):**

```
🌱 Good morning! Here are your garden tasks for today

🌤️ Weather: 21°C, sunny, no rain expected for 3 days

✅ Things to do today:
- Water the zucchinis (last watered 2 days ago, heat incoming)
- Check the cherry tomatoes (planted 14 days ago, watch for first flowers)
- No need to weed (done last week)
```

**Logging an action:**

```
You: I pruned the roses and added compost to the strawberries
Bot: ✅ Logged! I've saved:
- Roses pruned on May 6
- Compost added to strawberries on May 6
```

-----

## Tech Stack

|Component |Tool |Cost |
|-------------|-----------------------------------------------------------------|------|
|AI Brain |[Mistral AI](https://console.mistral.ai) (`mistral-small-latest`)|🆓 Free|
|Telegram Bot |[python-telegram-bot](https://python-telegram-bot.org) |🆓 Free|
|Garden Memory|[Notion API](https://developers.notion.com) |🆓 Free|
|Weather |[Open-Meteo](https://open-meteo.com) (no key needed) |🆓 Free|
|Scheduler |APScheduler |🆓 Free|

**Total cost: $0/month**

-----

## Requirements

- Python 3.10+
- A Fedora/Ubuntu/Linux machine running 24/7 (old PC works great)
- A Telegram account
- A Notion account
- A Mistral AI account

-----

## Installation

### 1. Clone the project

```bash
git clone https://github.com/yourname/garden-bot.git
cd garden-bot
```

### 2. Install dependencies

```bash
pip install python-telegram-bot mistralai notion-client requests apscheduler
```

### 3. Set up your API keys

Copy the example env file:

```bash
cp .env.example .env
```

Fill in your keys in `.env`:

```env
TELEGRAM_TOKEN=your_telegram_bot_token
MISTRAL_API_KEY=your_mistral_api_key
NOTION_TOKEN=your_notion_integration_token
NOTION_DATABASE_ID=your_notion_database_id
LATITUDE=48.8566 # your location (for weather)
LONGITUDE=2.3522
BRIEFING_HOUR=8 # hour to send the daily briefing (24h format)
```

### 4. Set up Notion

1. Go to [notion.so](https://notion.so) and create a new database called `Garden Log`
1. Add these properties to the database:

|Property|Type |
|--------|--------------------------------------------------------|
|Name |Title |
|Date |Date |
|Type |Select (watering, pruning, planting, fertilizing, other)|
|Plants |Multi-select |
|Notes |Text |

1. Go to [notion.so/my-integrations](https://notion.so/my-integrations), create a new integration, and copy the token
1. Share your `Garden Log` database with the integration

### 5. Get your Telegram bot token

1. Open Telegram and search for **@BotFather**
1. Send `/newbot` and follow the instructions
1. Copy the token BotFather gives you

### 6. Run the bot

```bash
python bot.py
```

### 7. Run on startup (optional but recommended)

Create a systemd service so the bot starts automatically:

```bash
# Create the service file
sudo nano /etc/systemd/system/garden-bot.service
```

Paste this content:

```ini
[Unit]
Description=Garden Assistant Bot
After=network.target

[Service]
ExecStart=/usr/bin/python3 /path/to/garden-bot/bot.py
WorkingDirectory=/path/to/garden-bot
Restart=always
User=your_username

[Install]
WantedBy=multi-user.target
```

Enable and start it:

```bash
sudo systemctl enable garden-bot
sudo systemctl start garden-bot
```

-----

## Project Structure

```
garden-bot/
├── bot.py # Main bot logic & Telegram handlers
├── memory.py # Notion read/write functions
├── weather.py # Open-Meteo API calls
├── advisor.py # Mistral AI prompt & response logic
├── scheduler.py # Daily briefing cron job
├── .env.example # Environment variables template
└── README.md
```

-----

## Bot Commands

|Command |Description |
|----------|--------------------------------|
|`/start` |Welcome message and instructions|
|`/today` |Get today’s task list manually |
|`/history`|Show last 10 logged actions |
|`/plants` |List all plants in your garden |
|`/help` |Show available commands |

You can also just **send a free-form message** to log any action:

> *“I watered the tomatoes and planted new basil near the peppers”*

-----

## How the Daily Briefing Works

Every morning at the configured hour, the bot automatically:

1. Fetches today’s weather forecast from Open-Meteo (temperature, rain, UV index)
1. Reads your last 30 garden actions from Notion
1. Sends everything to Mistral AI with a prompt asking for personalized task recommendations
1. Sends the result to your Telegram chat

-----

## Privacy

- All your garden data is stored in **your own Notion workspace**
- Weather is fetched from Open-Meteo using only your GPS coordinates (no account needed)
- No data is stored on any third-party server other than Mistral (for AI inference) and Notion (for memory)

-----

## License

MIT — do whatever you want with it 🌿

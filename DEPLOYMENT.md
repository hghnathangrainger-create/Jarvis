# Deployment Checklist

Complete guide for deploying Jarvis AI Operating System in production.

## Prerequisites

### System Requirements
- **Python**: 3.11 or higher
- **RAM**: 4GB minimum (8GB recommended)
- **CPU**: 2 cores minimum
- **Storage**: 10GB free space
- **OS**: Linux, macOS, or Windows

### Required Software
- [Poetry](https://python-poetry.org/) — dependency management
- [Git](https://git-scm.com/) — version control
- [Tesseract-OCR](https://github.com/tesseract-ocr/tesseract) — for OCR feature (optional)

### Install Tesseract (Linux)
```bash
sudo apt update
sudo apt install tesseract-ocr
```

### Install Tesseract (macOS)
```bash
brew install tesseract
```

## Environment Setup

### 1. Clone the Repository
```bash
git clone https://github.com/hghnathangrainger-create/Jarvis.git
cd Jarvis
```

### 2. Install Dependencies
```bash
poetry install
```

### 3. Configure Environment Variables
```bash
cp .env.example .env
```

Edit `.env` with your configuration:

```bash
# AI Providers (at least one required)
ANTHROPIC_API_KEY=your_claude_key
OPENAI_API_KEY=your_openai_key
GEMINI_API_KEY=your_gemini_key

# Ollama (optional, for free local fallback)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3

# API Server
API_HOST=0.0.0.0
API_PORT=8000
API_USERNAME=admin
API_PASSWORD=changeme
CORS_ORIGINS=http://localhost:3000

# Database
DATABASE_PATH=data/jarvis.db

# Voice (optional)
WAKE_WORD=hey jarvis
STT_PROVIDER=whisper
TTS_PROVIDER=pyttsx3

# Budget (optional)
COST_BUDGET_DAILY=10.00
COST_BUDGET_MONTHLY=200.00

# Security
SECURITY_INJECTION_SENSITIVITY=medium
SECURITY_APPROVAL_TTL_SECONDS=300

# Firebase (optional, for Android push notifications)
GOOGLE_FIREBASE_CREDENTIALS=path/to/service-account.json
```

## Running Jarvis

### CLI Mode
```bash
poetry run python -m jarvis.main
```

### Server Mode (API + Dashboard)
```bash
poetry run python -m jarvis.main --server
```

The dashboard will be available at: `http://localhost:8000/`
API docs will be available at: `http://localhost:8000/docs`

### Voice Mode
```bash
poetry run python -m jarvis.main --voice
```

### Safe Mode (GREEN-tier only)
```bash
poetry run python -m jarvis.main --safe-mode
```

## Testing

### Run All Tests
```bash
poetry run pytest -v
```

### Run Specific Test Files
```bash
poetry run pytest tests/unit/test_api.py -v
poetry run pytest tests/unit/test_agents.py -v
poetry run pytest tests/unit/test_security_v2.py -v
```

## Docker Deployment

### Dockerfile
```dockerfile
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && \
    apt-get install -y tesseract-ocr && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy dependency files
COPY pyproject.toml poetry.lock ./

# Install Poetry and dependencies
RUN pip install poetry && \
    poetry install --no-root --no-dev

# Copy application code
COPY . .

# Expose API port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/api/system/status')"

# Start the server
CMD ["poetry", "run", "python", "-m", "jarvis.main", "--server"]
```

### Build and Run
```bash
# Build the image
docker build -t jarvis .

# Run the container
docker run -d \
    --name jarvis \
    -p 8000:8000 \
    -v $(pwd)/.env:/app/.env \
    -v $(pwd)/data:/app/data \
    jarvis
```

### Docker Compose
```yaml
version: '3.8'

services:
  jarvis:
    build: .
    container_name: jarvis
    ports:
      - "8000:8000"
    volumes:
      - ./.env:/app/.env
      - ./data:/app/data
    restart: unless-stopped
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
```

## Production Deployment

### Nginx Reverse Proxy
```nginx
server {
    listen 80;
    server_name jarvis.yourdomain.com;

    # Redirect HTTP to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name jarvis.yourdomain.com;

    # SSL certificates (Let's Encrypt)
    ssl_certificate /etc/letsencrypt/live/jarvis.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/jarvis.yourdomain.com/privkey.pem;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options nosniff;
    add_header X-Frame-Options DENY;

    # Proxy to Jarvis
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # WebSocket support
    location /api/ws {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400;
    }
}
```

### Systemd Service
```ini
[Unit]
Description=Jarvis AI Operating System
After=network.target

[Service]
Type=simple
User=jarvis
Group=jarvis
WorkingDirectory=/opt/jarvis
Environment=PATH=/opt/jarvis/.venv/bin
ExecStart=/opt/jarvis/.venv/bin/python -m jarvis.main --server
Restart=always
RestartSec=10

# Security
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/jarvis/data

[Install]
WantedBy=multi-user.target
```

## Security Notes

### Critical
- **Change default API_PASSWORD immediately** — the default `changeme` is publicly known
- **Use HTTPS in production** — never expose the API over plain HTTP
- **Keep API keys out of git** — use `.env` file, never commit it
- **Set up a firewall** — only expose port 443 (HTTPS) or use a reverse proxy

### Recommended
- Use a dedicated database user with minimal permissions
- Enable rate limiting on the API (nginx `limit_req`)
- Set up monitoring and alerting
- Regular backups of the SQLite database
- Keep dependencies updated (`poetry update`)

### API Security
- JWT tokens expire after 24 hours by default
- All endpoints except `/api/system/status` and `/api/auth/login` require authentication
- GREEN actions auto-approve, YELLOW requires confirmation, RED requires explicit approval
- Prompt injection detection blocks malicious inputs

## Monitoring

### Health Check
```bash
curl http://localhost:8000/api/system/status
```

### API Metrics
```bash
curl -H "Authorization: Bearer <token>" http://localhost:8000/api/system/metrics
```

### Cost Tracking
```bash
curl -H "Authorization: Bearer <token>" http://localhost:8000/api/system/costs
```

## Troubleshooting

### Common Issues

1. **"No module named 'jarvis'"**
   - Make sure you're in the Jarvis directory
   - Run `poetry install` first

2. **"ANTHROPIC_API_KEY not set"**
   - Copy `.env.example` to `.env`
   - Add your API key to `.env`

3. **"Port 8000 already in use"**
   - Change `API_PORT` in `.env`
   - Or kill the process using the port: `lsof -ti:8000 | xargs kill -9`

4. **OCR not working**
   - Install Tesseract: `sudo apt install tesseract-ocr`
   - Check installation: `tesseract --version`

5. **Voice not working**
   - Install audio dependencies: `sudo apt install portaudio19-dev`
   - Install system TTS: `sudo apt install espeak`

## Support

- **Documentation**: See `docs/` directory
- **Issues**: https://github.com/hghnathangrainger-create/Jarvis/issues
- **API Docs**: http://localhost:8000/docs (when server is running)

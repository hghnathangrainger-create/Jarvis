# Jarvis Android App

A Kotlin/Jetpack Compose Android app that connects to the Jarvis AI Operating System API server.

## Features

- **Login** — Authenticate with JWT token
- **Chat** — Send messages and receive AI responses in real-time
- **Dashboard** — System status overview with all 16 subsystems
- **Memory** — Browse, search, and manage memories
- **Goals** — View and create goals with progress tracking
- **Settings** — Configure server, view providers, manage voice
- **Push Notifications** — Receive approval requests and alerts via FCM
- **Voice** — Record audio for speech-to-text input
- **Real-time Updates** — WebSocket connection for live events

## Requirements

- Android 8.0 (API 26) or higher
- Android Studio Hedgehog (2023.1.1) or later
- Kotlin 1.9.20+
- Gradle 8.2+

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/hghnathangrainger-create/Jarvis.git
cd Jarvis/JarvisAndroid
```

### 2. Open in Android Studio

Open the `JarvisAndroid` folder in Android Studio.

### 3. Configure Firebase (Optional)

For push notifications:

1. Create a Firebase project at https://console.firebase.google.com
2. Add an Android app with package name `com.jarvis.android`
3. Download `google-services.json` to the `app/` directory

### 4. Build and Run

```bash
./gradlew assembleDebug
```

Or use Android Studio's Run button.

## Configuration

### Server URL

The app defaults to `http://10.0.2.2:8000` (Android emulator's localhost). Change this in the login screen to point to your Jarvis server.

### Environment

| Setting | Default | Description |
|---------|---------|-------------|
| Server URL | `http://10.0.2.2:8000` | Jarvis API server address |
| Username | — | Your Jarvis username |
| Password | — | Your Jarvis password |

## Architecture

```
app/src/main/java/com/jarvis/android/
├── JarvisApp.kt                  # Application class with Hilt
├── MainActivity.kt               # Single activity
├── data/
│   ├── api/
│   │   ├── JarvisApi.kt          # Retrofit API interface
│   │   └── WebSocketClient.kt    # OkHttp WebSocket
│   ├── repository/
│   │   ├── AuthRepository.kt     # Authentication & token storage
│   │   ├── ChatRepository.kt     # Chat messages
│   │   └── MemoryRepository.kt   # Memory operations
│   └── model/                    # Data classes
├── di/
│   └── NetworkModule.kt          # Hilt dependency injection
├── ui/
│   ├── theme/Theme.kt            # Dark theme colors
│   ├── navigation/NavGraph.kt    # Navigation routes
│   └── screens/
│       ├── login/                 # Login screen
│       ├── chat/                  # Chat interface
│       ├── dashboard/             # System overview
│       ├── memory/                # Memory browser
│       ├── goals/                 # Goal tracking
│       └── settings/              # App settings
├── viewmodel/                     # ViewModels
└── service/
    ├── FCMService.kt             # Push notifications
    └── VoiceService.kt           # Audio recording
```

## Permissions

| Permission | Required | Purpose |
|------------|----------|---------|
| `INTERNET` | Yes | API communication |
| `RECORD_AUDIO` | Optional | Voice input |
| `POST_NOTIFICATIONS` | Optional | Push notifications (Android 13+) |

## API Integration

The app communicates with the Jarvis API server:

- **REST API** — Retrofit for HTTP requests
- **WebSocket** — OkHttp for real-time events
- **Authentication** — JWT tokens stored in DataStore

### Endpoints Used

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/auth/login` | POST | Authenticate |
| `/api/chat` | POST | Send messages |
| `/api/memory` | GET/POST/DELETE | Memory CRUD |
| `/api/goals` | GET/POST | Goal management |
| `/api/system/status` | GET | System health |
| `/api/system/providers` | GET | AI provider status |
| `/api/security/approvals` | GET | Pending approvals |
| `/api/ws` | WebSocket | Real-time events |

## Troubleshooting

### "Connection refused"

- Ensure the Jarvis server is running
- Check the server URL in settings
- For emulator, use `10.0.2.2` instead of `localhost`

### "Unauthorized"

- Your JWT token may have expired
- Log out and log in again

### Push notifications not working

- Ensure Firebase is configured
- Check notification permissions in Android settings
- Verify `google-services.json` is in the `app/` directory

## License

Part of the Jarvis AI Operating System project.

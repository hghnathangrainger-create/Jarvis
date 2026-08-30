# Android App Specification

Complete specification for the Jarvis Android companion app built with Kotlin/Jetpack Compose.

## Overview

The Jarvis Android app connects to the Jarvis API server, providing remote access to all Jarvis features including chat, workflow management, goals, memory, and voice interaction.

## Architecture

### Tech Stack
- **Language**: Kotlin 1.9+
- **UI Framework**: Jetpack Compose with Material 3
- **Architecture Pattern**: MVVM with Clean Architecture
- **Networking**: Retrofit + OkHttp for REST, OkHttp WebSocket for real-time
- **Dependency Injection**: Hilt
- **Local Storage**: DataStore for tokens, Room for offline cache
- **Async**: Kotlin Coroutines + Flow

### Project Structure
```
app/
├── data/
│   ├── remote/
│   │   ├── api/           # Retrofit API interfaces
│   │   ├── websocket/     # WebSocket client
│   │   └── models/        # DTOs (Data Transfer Objects)
│   ├── local/
│   │   ├── datastore/     # Token storage
│   │   └── database/      # Room database
│   └── repository/        # Repository implementations
├── domain/
│   ├── model/             # Domain models
│   ├── repository/        # Repository interfaces
│   └── usecase/           # Use cases
├── di/                    # Hilt modules
├── ui/
│   ├── theme/             # Material 3 theme
│   ├── navigation/        # Navigation graph
│   ├── screens/
│   │   ├── login/         # Login screen
│   │   ├── home/          # Home/dashboard
│   │   ├── chat/          # Chat interface
│   │   ├── workflows/     # Workflow management
│   │   ├── goals/         # Goal tracking
│   │   ├── memory/        # Memory browser
│   │   └── settings/      # Settings
│   └── components/        # Shared UI components
└── JarvisApp.kt           # Application class
```

## Screens

### 1. Login Screen
**Purpose**: Authenticate user and store JWT token

**UI Elements**:
- Username text field
- Password text field (with show/hide toggle)
- Login button
- Error message display
- Loading indicator

**API Calls**:
- `POST /api/auth/login` with `LoginRequest(username, password)`
- Stores `access_token` in encrypted DataStore

**Behavior**:
- On success: Navigate to Home screen
- On failure: Show error message
- On 401: Clear token, stay on login
- Auto-login if valid token exists

### 2. Home Screen
**Purpose**: System overview and quick actions

**UI Elements**:
- System status card (green/yellow/red indicator)
- Active workflows count
- Pending approvals count
- Quick action buttons:
  - Start Chat
  - View Workflows
  - View Goals
  - System Status

**API Calls**:
- `GET /api/system/status` (no auth required)
- `GET /api/workflows` (list active)
- `GET /api/security/approvals` (pending count)

**Behavior**:
- Auto-refresh every 30 seconds
- Tap status card to see detailed subsystem status

### 3. Chat Screen
**Purpose**: Send messages and receive AI responses

**UI Elements**:
- Message list (scrollable)
- Text input field
- Send button
- Mode selector (text/voice)
- Typing indicator

**API Calls**:
- `POST /api/chat` with `ChatRequest(message, mode)`
- Response includes `response`, `trace_id`, `provider`, `tokens_used`

**WebSocket**:
- Listen to `/api/ws` for real-time updates
- Events: new messages, system alerts

**Behavior**:
- Messages appear instantly
- Show provider and token usage
- Support for markdown rendering
- Long-press to copy message

### 4. Workflows Screen
**Purpose**: View and manage workflows

**UI Elements**:
- Workflow list with status indicators
- Progress bars for active workflows
- Approve/Deny buttons for pending steps
- Cancel button for running workflows
- Refresh button

**API Calls**:
- `GET /api/workflows` — list all
- `GET /api/workflows/{id}` — get details
- `POST /api/workflows/{id}/approve` — approve step
- `POST /api/workflows/{id}/cancel` — cancel workflow

**Behavior**:
- Pull-to-refresh
- Swipe to approve/deny
- Real-time updates via WebSocket
- Tap to expand step details

### 5. Goals Screen
**Purpose**: View and manage goals

**UI Elements**:
- Goal list with progress bars
- Priority badges (high/medium/low)
- Create new goal button
- Goal detail view with milestones
- Archive button

**API Calls**:
- `GET /api/goals` — list goals
- `POST /api/goals` — create goal
- `GET /api/projects` — list projects
- `GET /api/projects/{id}` — project status

**Behavior**:
- Progress bars update in real-time
- Tap to expand milestones
- Swipe to archive

### 6. Memory Screen
**Purpose**: Search and browse memories

**UI Elements**:
- Search bar
- Category filter chips
- Memory list with content preview
- Add memory button
- Delete button (with confirmation)

**API Calls**:
- `GET /api/memory` — list memories
- `GET /api/memory/search?q=...` — search
- `POST /api/memory` — add memory
- `DELETE /api/memory/{id}` — delete memory

**Behavior**:
- Real-time search as you type
- Filter by category
- Long-press to edit/delete

### 7. Settings Screen
**Purpose**: Configure app and view provider status

**UI Elements**:
- API server URL configuration
- AI provider status cards
- Voice settings toggle
- Budget display
- Logout button
- About section

**API Calls**:
- `GET /api/system/providers` — provider status
- `GET /api/system/costs` — cost summary

**Behavior**:
- Save server URL to DataStore
- Test connection on save
- Logout clears token

## API Integration

### Base Configuration
```kotlin
// ApiService.kt
interface JarvisApi {
    // Auth
    @POST("api/auth/login")
    suspend fun login(@Body request: LoginRequest): TokenResponse

    // Chat
    @POST("api/chat")
    suspend fun chat(@Body request: ChatRequest): ChatResponse

    // Memory
    @GET("api/memory")
    suspend fun getMemories(
        @Query("category") category: String? = null,
        @Query("limit") limit: Int = 50
    ): MemoryListResponse

    @GET("api/memory/search")
    suspend fun searchMemory(@Query("q") query: String): MemoryListResponse

    // Workflows
    @GET("api/workflows")
    suspend fun getWorkflows(): WorkflowListResponse

    @POST("api/workflows/{id}/approve")
    suspend fun approveWorkflow(@Path("id") id: String): ApprovalResponse

    // Goals
    @GET("api/goals")
    suspend fun getGoals(): GoalListResponse

    // System
    @GET("api/system/status")
    suspend fun getSystemStatus(): SystemStatusResponse
}
```

### Retrofit Setup
```kotlin
// NetworkModule.kt
@Module
@InstallIn(SingletonComponent::class)
object NetworkModule {

    @Provides
    @Singleton
    fun provideOkHttpClient(
        authInterceptor: AuthInterceptor
    ): OkHttpClient {
        return OkHttpClient.Builder()
            .addInterceptor(authInterceptor)
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .build()
    }

    @Provides
    @Singleton
    fun provideRetrofit(okHttpClient: OkHttpClient): Retrofit {
        return Retrofit.Builder()
            .baseUrl(BuildConfig.BASE_URL)
            .client(okHttpClient)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
    }
}
```

### Auth Interceptor
```kotlin
// AuthInterceptor.kt
class AuthInterceptor @Inject constructor(
    private val tokenManager: TokenManager
) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val token = tokenManager.getToken()
        val request = if (token != null) {
            chain.request().newBuilder()
                .addHeader("Authorization", "Bearer $token")
                .build()
        } else {
            chain.request()
        }
        return chain.proceed(request)
    }
}
```

### WebSocket Client
```kotlin
// WebSocketManager.kt
class WebSocketManager @Inject constructor(
    private val okHttpClient: OkHttpClient,
    private val tokenManager: TokenManager
) {
    private var webSocket: WebSocket? = null
    private val _events = MutableSharedFlow<WsEvent>()
    val events: SharedFlow<WsEvent> = _events

    fun connect(baseUrl: String) {
        val token = tokenManager.getToken() ?: return
        val url = baseUrl.replace("http", "ws") + "/api/ws?token=$token"

        val request = Request.Builder()
            .url(url)
            .build()

        webSocket = okHttpClient.newWebSocket(request, object : WebSocketListener() {
            override fun onMessage(webSocket: WebSocket, text: String) {
                val event = Gson().fromJson(text, WsEvent::class.java)
                CoroutineScope(Dispatchers.IO).launch {
                    _events.emit(event)
                }
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                // Reconnect after 5 seconds
                CoroutineScope(Dispatchers.IO).launch {
                    delay(5000)
                    connect(baseUrl)
                }
            }
        })
    }

    fun disconnect() {
        webSocket?.close(1000, "Client disconnect")
    }
}
```

## Push Notifications

### Firebase Setup
1. Create Firebase project at https://console.firebase.google.com
2. Add Android app with package name `com.jarvis.app`
3. Download `google-services.json` to `app/` directory
4. Add Firebase dependencies

### FCM Registration
```kotlin
// FCMService.kt
class FCMService : FirebaseMessagingService() {

    @Inject
    lateinit var apiService: JarvisApi

    override fun onNewToken(token: String) {
        super.onNewToken(token)
        CoroutineScope(Dispatchers.IO).launch {
            apiService.registerDevice(
                DeviceRegistration(
                    device_id = getDeviceId(),
                    fcm_token = token,
                    platform = "android"
                )
            )
        }
    }

    override fun onMessageReceived(message: RemoteMessage) {
        super.onMessageReceived(message)

        when (message.data["type"]) {
            "approval_request" -> showApprovalNotification(message)
            "task_completion" -> showTaskNotification(message)
            "alert" -> showAlertNotification(message)
        }
    }

    private fun showApprovalNotification(message: RemoteMessage) {
        val requestId = message.data["request_id"] ?: return
        val action = message.data["action"] ?: ""
        val details = message.data["details"] ?: ""

        val approveIntent = Intent(this, ApprovalReceiver::class.java).apply {
            action = "APPROVE"
            putExtra("request_id", requestId)
        }
        val denyIntent = Intent(this, ApprovalReceiver::class.java).apply {
            action = "DENY"
            putExtra("request_id", requestId)
        }

        val pendingApprove = PendingIntent.getBroadcast(
            this, 0, approveIntent, PendingIntent.FLAG_IMMUTABLE
        )
        val pendingDeny = PendingIntent.getBroadcast(
            this, 1, denyIntent, PendingIntent.FLAG_IMMUTABLE
        )

        val notification = NotificationCompat.Builder(this, "approvals")
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle("Approval Required")
            .setContentText("$action: $details")
            .addAction(R.drawable.ic_approve, "Approve", pendingApprove)
            .addAction(R.drawable.ic_deny, "Deny", pendingDeny)
            .setAutoCancel(true)
            .build()

        NotificationManagerCompat.from(this).notify(requestId.hashCode(), notification)
    }
}
```

## Voice Integration

### Audio Recording
```kotlin
// VoiceManager.kt
class VoiceManager @Inject constructor(
    private val apiService: JarvisApi
) {
    private var audioRecorder: AudioRecorder? = null

    suspend fun startListening(): Flow<String> = callbackFlow {
        audioRecorder = AudioRecorder().apply {
            startRecording()
        }

        // Record for 5 seconds or until silence
        delay(5000)
        val audioData = audioRecorder?.stopRecording()

        if (audioData != null) {
            // Send to Jarvis API for STT
            val response = apiService.transcribeAudio(audioData)
            send(response.text)
        }

        close()
    }

    suspend fun playAudio(audioUrl: String) {
        // Download and play TTS audio from Jarvis
        val mediaPlayer = MediaPlayer()
        mediaPlayer.setDataSource(audioUrl)
        mediaPlayer.prepare()
        mediaPlayer.start()
    }
}
```

## Key Dependencies

### build.gradle.kts (app)
```kotlin
dependencies {
    // Core
    implementation("androidx.core:core-ktx:1.12.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.7.0")
    implementation("androidx.activity:activity-compose:1.8.2")

    // Compose
    implementation(platform("androidx.compose:compose-bom:2024.01.00"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.navigation:navigation-compose:2.7.7")

    // API
    implementation("com.squareup.retrofit2:retrofit:2.9.0")
    implementation("com.squareup.retrofit2:converter-gson:2.9.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.squareup.okhttp3:logging-interceptor:4.12.0")

    // WebSocket
    implementation("com.squareup.okhttp3:okhttp-ws:4.12.0")

    // Firebase
    implementation(platform("com.google.firebase:firebase-bom:32.7.0"))
    implementation("com.google.firebase:firebase-messaging-ktx")

    // DI
    implementation("com.google.dagger:hilt-android:2.50")
    kapt("com.google.dagger:hilt-compiler:2.50")
    implementation("androidx.hilt:hilt-navigation-compose:1.1.0")

    // DataStore
    implementation("androidx.datastore:datastore-preferences:1.0.0")

    // Room (offline cache)
    implementation("androidx.room:room-runtime:2.6.1")
    implementation("androidx.room:room-ktx:2.6.1")
    kapt("androidx.room:room-compiler:2.6.1")

    // Coil (image loading)
    implementation("io.coil-kt:coil-compose:2.5.0")

    // Testing
    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test.ext:junit:1.1.5")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.5.1")
    androidTestImplementation(platform("androidx.compose:compose-bom:2024.01.00"))
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")
    debugImplementation("androidx.compose.ui:ui-tooling")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
}
```

## Permissions

### AndroidManifest.xml
```xml
<uses-permission android:name="android.permission.INTERNET" />
<uses-permission android:name="android.permission.RECORD_AUDIO" />
<uses-permission android:name="android.permission.POST_NOTIFICATIONS" />
<uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />

<application
    android:name=".JarvisApp"
    android:allowBackup="true"
    android:icon="@mipmap/ic_launcher"
    android:label="@string/app_name"
    android:supportsRtl="true"
    android:theme="@style/Theme.Jarvis">
    <!-- ... -->
</application>
```

## Navigation

### NavGraph.kt
```kotlin
@Composable
fun JarvisNavGraph(
    navController: NavHostController,
    viewModel: MainViewModel
) {
    NavHost(navController = navController, startDestination = "login") {
        composable("login") {
            LoginScreen(
                onLoginSuccess = {
                    navController.navigate("home") {
                        popUpTo("login") { inclusive = true }
                    }
                }
            )
        }
        composable("home") {
            HomeScreen(
                onNavigate = { route -> navController.navigate(route) }
            )
        }
        composable("chat") {
            ChatScreen()
        }
        composable("workflows") {
            WorkflowsScreen()
        }
        composable("goals") {
            GoalsScreen()
        }
        composable("memory") {
            MemoryScreen()
        }
        composable("settings") {
            SettingsScreen(
                onLogout = {
                    navController.navigate("login") {
                        popUpTo(0) { inclusive = true }
                    }
                }
            )
        }
    }
}
```

## Error Handling

### Network Errors
```kotlin
// ApiResult.kt
sealed class ApiResult<out T> {
    data class Success<T>(val data: T) : ApiResult<T>()
    data class Error(val code: Int, val message: String) : ApiResult<Nothing>()
    data class Exception(val throwable: Throwable) : ApiResult<Nothing>()
}

// Retry logic
suspend fun <T> safeApiCall(
    apiCall: suspend () -> T
): ApiResult<T> {
    return try {
        ApiResult.Success(apiCall())
    } catch (e: HttpException) {
        when (e.code()) {
            401 -> ApiResult.Error(401, "Unauthorized")
            404 -> ApiResult.Error(404, "Not found")
            else -> ApiResult.Error(e.code(), e.message())
        }
    } catch (e: IOException) {
        ApiResult.Exception(e)
    }
}
```

## Testing

### Unit Tests
- ViewModel logic
- Repository implementations
- Use cases
- API response parsing

### UI Tests
- Screenshot tests for each screen
- Navigation tests
- Form validation tests

### Integration Tests
- API client tests with mock server
- WebSocket connection tests
- End-to-end login flow

## Build Configuration

### build.gradle.kts (app)
```kotlin
android {
    namespace = "com.jarvis.app"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.jarvis.app"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "1.0.0"

        buildConfigField("String", "BASE_URL", "\"http://10.0.2.2:8000/\"")
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
        debug {
            isMinifyEnabled = false
            applicationIdSuffix = ".debug"
        }
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }
}
```

## Distribution

### Google Play Store
1. Create developer account at https://play.google.com/console
2. Generate signed APK/AAB
3. Fill in store listing
4. Set pricing and distribution
5. Submit for review

### Direct Distribution
1. Build release APK: `./gradlew assembleRelease`
2. Share APK file directly
3. Users enable "Install from unknown sources"

## Future Enhancements

- [ ] Offline mode with local caching
- [ ] Biometric authentication
- [ ] Widget for quick actions
- [ ] Wear OS companion app
- [ ] Tablet-optimized layouts
- [ ] Dark/Light theme toggle
- [ ] Custom notification sounds
- [ ] Shortcuts for common actions

package com.jarvis.android

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.ui.Modifier
import androidx.navigation.compose.rememberNavController
import com.jarvis.android.data.api.WebSocketClient
import com.jarvis.android.data.repository.AuthRepository
import com.jarvis.android.ui.navigation.NavGraph
import com.jarvis.android.ui.navigation.Screen
import com.jarvis.android.ui.theme.JarvisTheme
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.runBlocking
import javax.inject.Inject

@AndroidEntryPoint
class MainActivity : ComponentActivity() {

    @Inject
    lateinit var authRepository: AuthRepository

    @Inject
    lateinit var webSocketClient: WebSocketClient

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        setContent {
            JarvisTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    val navController = rememberNavController()
                    val startDestination = if (runBlocking { authRepository.isLoggedIn() }) {
                        Screen.Dashboard.route
                    } else {
                        Screen.Login.route
                    }

                    // Connect WebSocket if logged in
                    if (startDestination == Screen.Dashboard.route) {
                        runBlocking {
                            val token = authRepository.getToken()
                            val serverUrl = authRepository.getServerUrl()
                            if (token != null && serverUrl != null) {
                                webSocketClient.connect(serverUrl, token)
                            }
                        }
                    }

                    NavGraph(
                        navController = navController,
                        startDestination = startDestination
                    )
                }
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        webSocketClient.disconnect()
    }
}

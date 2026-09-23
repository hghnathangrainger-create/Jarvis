package com.jarvis.android.ui.screens.settings

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jarvis.android.data.api.JarvisApi
import com.jarvis.android.data.api.WebSocketClient
import com.jarvis.android.data.model.ProviderStatus
import com.jarvis.android.data.repository.AuthRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class SettingsUiState(
    val serverUrl: String = "",
    val username: String = "",
    val providers: List<ProviderStatus> = emptyList(),
    val voiceEnabled: Boolean = false,
    val version: String = "1.0.0",
    val systemStatus: String = "Unknown"
)

@HiltViewModel
class SettingsViewModel @Inject constructor(
    private val api: JarvisApi,
    private val authRepository: AuthRepository,
    private val webSocketClient: WebSocketClient
) : ViewModel() {

    private val _uiState = MutableStateFlow(SettingsUiState())
    val uiState: StateFlow<SettingsUiState> = _uiState.asStateFlow()

    init {
        loadSettings()
    }

    private fun loadSettings() {
        viewModelScope.launch {
            val serverUrl = authRepository.getServerUrl() ?: ""
            val username = authRepository.getUsername() ?: ""
            _uiState.update { it.copy(serverUrl = serverUrl, username = username) }

            // Load providers
            try {
                val response = api.getProviders()
                if (response.isSuccessful) {
                    _uiState.update {
                        it.copy(providers = response.body()?.providers ?: emptyList())
                    }
                }
            } catch (e: Exception) {
                // Ignore
            }

            // Load system status
            try {
                val response = api.getSystemStatus()
                if (response.isSuccessful) {
                    _uiState.update {
                        it.copy(
                            version = response.body()?.version ?: "1.0.0",
                            systemStatus = response.body()?.status ?: "Unknown"
                        )
                    }
                }
            } catch (e: Exception) {
                // Ignore
            }
        }
    }

    fun toggleVoice() {
        _uiState.update { it.copy(voiceEnabled = !it.voiceEnabled) }
    }

    fun logout() {
        viewModelScope.launch {
            authRepository.logout()
            webSocketClient.disconnect()
        }
    }
}

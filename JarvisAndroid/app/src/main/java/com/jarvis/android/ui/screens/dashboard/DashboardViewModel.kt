package com.jarvis.android.ui.screens.dashboard

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jarvis.android.data.api.JarvisApi
import com.jarvis.android.data.api.WebSocketClient
import com.jarvis.android.data.model.SystemStatus
import com.jarvis.android.data.model.WsEvent
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class DashboardUiState(
    val systemStatus: SystemStatus? = null,
    val isConnected: Boolean = false,
    val isLoading: Boolean = false,
    val error: String? = null
)

@HiltViewModel
class DashboardViewModel @Inject constructor(
    private val api: JarvisApi,
    private val webSocketClient: WebSocketClient
) : ViewModel() {

    private val _uiState = MutableStateFlow(DashboardUiState())
    val uiState: StateFlow<DashboardUiState> = _uiState.asStateFlow()

    init {
        loadSystemStatus()

        // Listen for WebSocket connection state
        viewModelScope.launch {
            webSocketClient.connectionState.collect { state ->
                _uiState.update {
                    it.copy(isConnected = state == WebSocketClient.ConnectionState.CONNECTED)
                }
            }
        }

        // Listen for real-time updates
        viewModelScope.launch {
            webSocketClient.events.collect { event ->
                handleEvent(event)
            }
        }
    }

    private fun loadSystemStatus() {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true) }
            try {
                val response = api.getSystemStatus()
                if (response.isSuccessful) {
                    _uiState.update {
                        it.copy(
                            systemStatus = response.body(),
                            isLoading = false
                        )
                    }
                }
            } catch (e: Exception) {
                _uiState.update {
                    it.copy(
                        isLoading = false,
                        error = e.message
                    )
                }
            }
        }
    }

    private fun handleEvent(event: WsEvent) {
        when (event.type) {
            "system_update" -> {
                loadSystemStatus()
            }
        }
    }

    fun refresh() {
        loadSystemStatus()
    }
}

package com.jarvis.android.ui.screens.chat

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jarvis.android.data.api.WebSocketClient
import com.jarvis.android.data.model.ChatMessage
import com.jarvis.android.data.model.WsEvent
import com.jarvis.android.data.repository.ChatRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class ChatUiState(
    val messages: List<ChatMessage> = emptyList(),
    val inputText: String = "",
    val isLoading: Boolean = false,
    val isTyping: Boolean = false,
    val isRecording: Boolean = false,
    val connectionState: WebSocketClient.ConnectionState = WebSocketClient.ConnectionState.DISCONNECTED,
    val error: String? = null
)

@HiltViewModel
class ChatViewModel @Inject constructor(
    private val chatRepository: ChatRepository,
    private val webSocketClient: WebSocketClient
) : ViewModel() {

    private val _uiState = MutableStateFlow(ChatUiState())
    val uiState: StateFlow<ChatUiState> = _uiState.asStateFlow()

    init {
        // Load existing messages
        _uiState.update { it.copy(messages = chatRepository.getMessages()) }

        // Listen for WebSocket events
        viewModelScope.launch {
            webSocketClient.connectionState.collect { state ->
                _uiState.update { it.copy(connectionState = state) }
            }
        }

        // Listen for WebSocket messages
        viewModelScope.launch {
            webSocketClient.events.collect { event ->
                handleWebSocketEvent(event)
            }
        }
    }

    private fun handleWebSocketEvent(event: WsEvent) {
        when (event.type) {
            "new_message" -> {
                val content = event.data["content"] as? String ?: return
                val message = ChatMessage(
                    content = content,
                    isUser = false
                )
                _uiState.update { state ->
                    state.copy(messages = state.messages + message)
                }
            }
            "approval_request" -> {
                val action = event.data["action"] as? String ?: "Unknown action"
                val message = ChatMessage(
                    content = "⚠️ Approval required: $action",
                    isUser = false
                )
                _uiState.update { state ->
                    state.copy(messages = state.messages + message)
                }
            }
        }
    }

    fun updateInputText(text: String) {
        _uiState.update { it.copy(inputText = text) }
    }

    fun sendMessage() {
        val text = _uiState.value.inputText.trim()
        if (text.isBlank()) return

        // Add user message
        val userMessage = chatRepository.addUserMessage(text)
        _uiState.update { state ->
            state.copy(
                messages = state.messages + userMessage,
                inputText = "",
                isTyping = true
            )
        }

        // Send to API
        viewModelScope.launch {
            val result = chatRepository.sendMessage(text)
            result.fold(
                onSuccess = { botMessage ->
                    _uiState.update { state ->
                        state.copy(
                            messages = state.messages + botMessage,
                            isTyping = false
                        )
                    }
                },
                onFailure = { exception ->
                    _uiState.update { state ->
                        state.copy(
                            isTyping = false,
                            error = exception.message
                        )
                    }
                }
            )
        }
    }

    fun toggleVoiceRecording() {
        _uiState.update { it.copy(isRecording = !it.isRecording) }
        // TODO: Implement voice recording
    }
}

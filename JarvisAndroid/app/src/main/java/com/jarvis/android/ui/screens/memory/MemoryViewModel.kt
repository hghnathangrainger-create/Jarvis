package com.jarvis.android.ui.screens.memory

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jarvis.android.data.model.Memory
import com.jarvis.android.data.repository.MemoryRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class MemoryUiState(
    val memories: List<Memory> = emptyList(),
    val selectedCategory: String? = null,
    val isLoading: Boolean = false,
    val error: String? = null
)

@HiltViewModel
class MemoryViewModel @Inject constructor(
    private val memoryRepository: MemoryRepository
) : ViewModel() {

    private val _uiState = MutableStateFlow(MemoryUiState())
    val uiState: StateFlow<MemoryUiState> = _uiState.asStateFlow()

    init {
        loadMemories()
    }

    fun loadMemories(category: String? = null) {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, selectedCategory = category) }
            val result = memoryRepository.getMemories(category)
            result.fold(
                onSuccess = { memories ->
                    _uiState.update { it.copy(memories = memories, isLoading = false) }
                },
                onFailure = { exception ->
                    _uiState.update { it.copy(isLoading = false, error = exception.message) }
                }
            )
        }
    }

    fun searchMemories(query: String) {
        if (query.isBlank()) {
            loadMemories()
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true) }
            val result = memoryRepository.searchMemories(query)
            result.fold(
                onSuccess = { memories ->
                    _uiState.update { it.copy(memories = memories, isLoading = false) }
                },
                onFailure = { exception ->
                    _uiState.update { it.copy(isLoading = false, error = exception.message) }
                }
            )
        }
    }

    fun createMemory(content: String, category: String) {
        viewModelScope.launch {
            val result = memoryRepository.createMemory(content, category)
            result.fold(
                onSuccess = {
                    loadMemories(_uiState.value.selectedCategory)
                },
                onFailure = { exception ->
                    _uiState.update { it.copy(error = exception.message) }
                }
            )
        }
    }

    fun deleteMemory(id: Int) {
        viewModelScope.launch {
            val result = memoryRepository.deleteMemory(id)
            result.fold(
                onSuccess = {
                    loadMemories(_uiState.value.selectedCategory)
                },
                onFailure = { exception ->
                    _uiState.update { it.copy(error = exception.message) }
                }
            )
        }
    }
}

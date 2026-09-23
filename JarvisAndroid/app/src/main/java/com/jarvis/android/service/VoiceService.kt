package com.jarvis.android.service

import android.app.Service
import android.content.Intent
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Binder
import android.os.IBinder
import android.util.Log
import kotlinx.coroutines.*
import java.io.ByteArrayOutputStream
import javax.inject.Inject

class VoiceService : Service() {

    companion object {
        private const val TAG = "VoiceService"
        private const val SAMPLE_RATE = 16000
        private const val CHANNEL_CONFIG = AudioFormat.CHANNEL_IN_MONO
        private const val AUDIO_FORMAT = AudioFormat.ENCODING_PCM_16BIT
    }

    private val binder = VoiceBinder()
    private var audioRecord: AudioRecord? = null
    private var isRecording = false
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private val _recordingState = kotlinx.coroutines.flow.MutableSharedFlow<RecordingState>(replay = 1)
    val recordingState: kotlinx.coroutines.flow.SharedFlow<RecordingState> = _recordingState

    inner class VoiceBinder : Binder() {
        fun getService(): VoiceService = this@VoiceService
    }

    override fun onBind(intent: Intent): IBinder {
        return binder
    }

    fun startRecording() {
        if (isRecording) return

        val bufferSize = AudioRecord.getMinBufferSize(SAMPLE_RATE, CHANNEL_CONFIG, AUDIO_FORMAT)
        if (bufferSize == AudioRecord.ERROR || bufferSize == AudioRecord.ERROR_BAD_VALUE) {
            Log.e(TAG, "Invalid buffer size")
            return
        }

        try {
            audioRecord = AudioRecord(
                MediaRecorder.AudioSource.MIC,
                SAMPLE_RATE,
                CHANNEL_CONFIG,
                AUDIO_FORMAT,
                bufferSize
            )

            if (audioRecord?.state != AudioRecord.STATE_INITIALIZED) {
                Log.e(TAG, "AudioRecord failed to initialize")
                return
            }

            audioRecord?.startRecording()
            isRecording = true

            scope.launch {
                _recordingState.emit(RecordingState.RECORDING)
                val audioData = captureAudio()
                if (audioData != null) {
                    _recordingState.emit(RecordingState.PROCESSING)
                    // Audio data will be processed by the caller
                    _recordingState.emit(RecordingState.COMPLETED)
                }
            }

            Log.d(TAG, "Recording started")
        } catch (e: SecurityException) {
            Log.e(TAG, "Microphone permission not granted", e)
        } catch (e: Exception) {
            Log.e(TAG, "Failed to start recording", e)
        }
    }

    fun stopRecording(): ByteArray? {
        if (!isRecording) return null

        isRecording = false
        audioRecord?.stop()
        audioRecord?.release()
        audioRecord = null

        Log.d(TAG, "Recording stopped")
        return null
    }

    private suspend fun captureAudio(): ByteArray? {
        val bufferSize = AudioRecord.getMinBufferSize(SAMPLE_RATE, CHANNEL_CONFIG, AUDIO_FORMAT)
        val outputStream = ByteArrayOutputStream()

        return withContext(Dispatchers.IO) {
            try {
                val buffer = ShortArray(bufferSize / 2)
                while (isRecording) {
                    val read = audioRecord?.read(buffer, 0, buffer.size) ?: 0
                    if (read > 0) {
                        // Convert short to bytes
                        for (i in 0 until read) {
                            val value = buffer[i]
                            outputStream.write(value.toInt() and 0xFF)
                            outputStream.write((value.toInt() shr 8) and 0xFF)
                        }
                    }
                }
                outputStream.toByteArray()
            } catch (e: Exception) {
                Log.e(TAG, "Error capturing audio", e)
                null
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        stopRecording()
        scope.cancel()
    }

    enum class RecordingState {
        IDLE,
        RECORDING,
        PROCESSING,
        COMPLETED,
        ERROR
    }
}

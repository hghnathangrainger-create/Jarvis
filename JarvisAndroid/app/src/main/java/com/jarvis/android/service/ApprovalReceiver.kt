package com.jarvis.android.service

import android.app.NotificationManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import com.jarvis.android.data.api.JarvisApi
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import javax.inject.Inject

@AndroidEntryPoint
class ApprovalReceiver : BroadcastReceiver() {

    @Inject
    lateinit var api: JarvisApi

    override fun onReceive(context: Context, intent: Intent) {
        val requestId = intent.getStringExtra("request_id") ?: return
        val action = intent.action ?: return

        Log.d("ApprovalReceiver", "Received action: $action for request: $requestId")

        CoroutineScope(Dispatchers.IO).launch {
            try {
                when (action) {
                    "APPROVE" -> {
                        api.approveRequest(requestId)
                        Log.d("ApprovalReceiver", "Approved request: $requestId")
                    }
                    "DENY" -> {
                        api.denyRequest(requestId)
                        Log.d("ApprovalReceiver", "Denied request: $requestId")
                    }
                }

                // Dismiss notification
                val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
                manager.cancel(requestId.hashCode())
            } catch (e: Exception) {
                Log.e("ApprovalReceiver", "Failed to process approval", e)
            }
        }
    }
}

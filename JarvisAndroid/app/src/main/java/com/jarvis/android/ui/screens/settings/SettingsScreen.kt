package com.jarvis.android.ui.screens.settings

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import com.jarvis.android.ui.theme.*

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    onLogout: () -> Unit,
    viewModel: SettingsViewModel = hiltViewModel()
) {
    val uiState by viewModel.uiState.collectAsState()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Color(0xFF0A0A0F))
    ) {
        // Top bar
        TopAppBar(
            title = {
                Text(
                    "Settings",
                    color = Color.White,
                    fontWeight = FontWeight.Bold
                )
            },
            colors = TopAppBarDefaults.topAppBarColors(
                containerColor = Surface
            )
        )

        LazyColumn(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            // Server Section
            item {
                SectionHeader("Server")
            }

            item {
                SettingsCard {
                    Column {
                        SettingsItem(
                            icon = Icons.Default.Language,
                            title = "Server URL",
                            subtitle = uiState.serverUrl
                        )
                        Divider(color = Color(0xFF333333))
                        SettingsItem(
                            icon = Icons.Default.Person,
                            title = "Username",
                            subtitle = uiState.username
                        )
                    }
                }
            }

            // AI Providers Section
            item {
                SectionHeader("AI Providers")
            }

            item {
                SettingsCard {
                    Column {
                        uiState.providers.forEach { provider ->
                            ProviderItem(
                                name = provider.name,
                                available = provider.available
                            )
                            if (provider != uiState.providers.last()) {
                                Divider(color = Color(0xFF333333))
                            }
                        }
                        if (uiState.providers.isEmpty()) {
                            Text(
                                "No providers configured",
                                color = Color(0xFF666666),
                                modifier = Modifier.padding(16.dp)
                            )
                        }
                    }
                }
            }

            // Voice Section
            item {
                SectionHeader("Voice")
            }

            item {
                SettingsCard {
                    SettingsToggleItem(
                        icon = Icons.Default.Mic,
                        title = "Voice Input",
                        checked = uiState.voiceEnabled,
                        onCheckedChange = { viewModel.toggleVoice() }
                    )
                }
            }

            // About Section
            item {
                SectionHeader("About")
            }

            item {
                SettingsCard {
                    Column {
                        SettingsItem(
                            icon = Icons.Default.Info,
                            title = "Version",
                            subtitle = uiState.version
                        )
                        Divider(color = Color(0xFF333333))
                        SettingsItem(
                            icon = Icons.Default.Storage,
                            title = "Status",
                            subtitle = uiState.systemStatus
                        )
                    }
                }
            }

            // Logout
            item {
                Spacer(modifier = Modifier.height(16.dp))
                Button(
                    onClick = {
                        viewModel.logout()
                        onLogout()
                    },
                    modifier = Modifier.fillMaxWidth(),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = StatusRed
                    ),
                    shape = RoundedCornerShape(8.dp)
                ) {
                    Icon(
                        Icons.Default.Logout,
                        contentDescription = null,
                        modifier = Modifier.size(20.dp)
                    )
                    Spacer(modifier = Modifier.width(8.dp))
                    Text("Logout")
                }
            }
        }
    }
}

@Composable
fun SectionHeader(title: String) {
    Text(
        title,
        color = Primary,
        fontWeight = FontWeight.Bold,
        fontSize = 14.sp,
        modifier = Modifier.padding(vertical = 4.dp)
    )
}

@Composable
fun SettingsCard(content: @Composable () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = Surface),
        shape = RoundedCornerShape(12.dp)
    ) {
        content()
    }
}

@Composable
fun SettingsItem(
    icon: ImageVector,
    title: String,
    subtitle: String
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(16.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Icon(
            icon,
            contentDescription = null,
            tint = Primary,
            modifier = Modifier.size(24.dp)
        )
        Spacer(modifier = Modifier.width(16.dp))
        Column {
            Text(
                title,
                color = Color.White,
                fontSize = 14.sp
            )
            Text(
                subtitle,
                color = Color(0xFF888888),
                fontSize = 12.sp
            )
        }
    }
}

@Composable
fun SettingsToggleItem(
    icon: ImageVector,
    title: String,
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(16.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(
                icon,
                contentDescription = null,
                tint = Primary,
                modifier = Modifier.size(24.dp)
            )
            Spacer(modifier = Modifier.width(16.dp))
            Text(
                title,
                color = Color.White,
                fontSize = 14.sp
            )
        }
        Switch(
            checked = checked,
            onCheckedChange = onCheckedChange,
            colors = SwitchDefaults.colors(
                checkedThumbColor = Color.White,
                checkedTrackColor = Primary,
                uncheckedThumbColor = Color(0xFF888888),
                uncheckedTrackColor = Color(0xFF333333)
            )
        )
    }
}

@Composable
fun ProviderItem(name: String, available: Boolean) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(16.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Text(
            name,
            color = Color.White,
            fontSize = 14.sp
        )
        Box(
            modifier = Modifier
                .size(12.dp)
                .clip(RoundedCornerShape(6.dp))
                .background(if (available) StatusGreen else StatusRed)
        )
    }
}

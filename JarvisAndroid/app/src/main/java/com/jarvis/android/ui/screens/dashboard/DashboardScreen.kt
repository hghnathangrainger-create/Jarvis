package com.jarvis.android.ui.screens.dashboard

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
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
import com.jarvis.android.ui.navigation.Screen
import com.jarvis.android.ui.theme.*

data class DashboardItem(
    val title: String,
    val icon: ImageVector,
    val route: String,
    val status: String? = null
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DashboardScreen(
    onNavigate: (String) -> Unit,
    viewModel: DashboardViewModel = hiltViewModel()
) {
    val uiState by viewModel.uiState.collectAsState()

    val dashboardItems = listOf(
        DashboardItem("Chat", Icons.Default.Chat, Screen.Chat.route),
        DashboardItem("Memory", Icons.Default.Memory, Screen.Memory.route),
        DashboardItem("Goals", Icons.Default.Flag, Screen.Goals.route),
        DashboardItem("Workflows", Icons.Default.AccountTree, "workflows"),
        DashboardItem("Security", Icons.Default.Security, "security"),
        DashboardItem("Settings", Icons.Default.Settings, Screen.Settings.route)
    )

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Color(0xFF0A0A0F))
    ) {
        // Top bar
        TopAppBar(
            title = {
                Column {
                    Text(
                        "Jarvis",
                        color = Color.White,
                        fontWeight = FontWeight.Bold,
                        fontSize = 20.sp
                    )
                    Text(
                        "AI Operating System",
                        color = Color(0xFFB0B0B0),
                        fontSize = 12.sp
                    )
                }
            },
            colors = TopAppBarDefaults.topAppBarColors(
                containerColor = Surface
            ),
            actions = {
                // Connection status
                Box(
                    modifier = Modifier
                        .padding(8.dp)
                        .size(12.dp)
                        .clip(RoundedCornerShape(6.dp))
                        .background(if (uiState.isConnected) StatusGreen else StatusRed)
                )
            }
        )

        // System Status Card
        Card(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            colors = CardDefaults.cardColors(containerColor = Surface),
            shape = RoundedCornerShape(12.dp)
        ) {
            Column(
                modifier = Modifier.padding(16.dp)
            ) {
                Text(
                    "System Status",
                    color = Color.White,
                    fontWeight = FontWeight.Bold,
                    fontSize = 16.sp
                )
                Spacer(modifier = Modifier.height(8.dp))

                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    StatusItem("Status", uiState.systemStatus?.status ?: "Unknown")
                    StatusItem("Version", uiState.systemStatus?.version ?: "N/A")
                    StatusItem("Uptime", formatUptime(uiState.systemStatus?.uptime ?: 0.0))
                }

                // Subsystems
                Spacer(modifier = Modifier.height(12.dp))
                Text(
                    "Subsystems",
                    color = Color(0xFFB0B0B0),
                    fontSize = 12.sp
                )
                Spacer(modifier = Modifier.height(8.dp))

                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    uiState.systemStatus?.subsystems?.forEach { (name, active) ->
                        SubsystemChip(name, active)
                    }
                }
            }
        }

        // Quick Actions Grid
        Text(
            "Quick Actions",
            color = Color.White,
            fontWeight = FontWeight.Bold,
            fontSize = 16.sp,
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp)
        )

        LazyVerticalGrid(
            columns = GridCells.Fixed(2),
            modifier = Modifier.padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            items(dashboardItems) { item ->
                DashboardCard(
                    item = item,
                    onClick = { onNavigate(item.route) }
                )
            }
        }
    }
}

@Composable
fun StatusItem(label: String, value: String) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(
            value,
            color = Primary,
            fontWeight = FontWeight.Bold,
            fontSize = 14.sp
        )
        Text(
            label,
            color = Color(0xFF888888),
            fontSize = 10.sp
        )
    }
}

@Composable
fun SubsystemChip(name: String, active: Boolean) {
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(4.dp))
            .background(if (active) StatusGreen.copy(alpha = 0.2f) else StatusRed.copy(alpha = 0.2f))
            .padding(horizontal = 8.dp, vertical = 4.dp)
    ) {
        Text(
            name,
            color = if (active) StatusGreen else StatusRed,
            fontSize = 10.sp
        )
    }
}

@Composable
fun DashboardCard(item: DashboardItem, onClick: () -> Unit) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .height(100.dp)
            .clickable(onClick = onClick),
        colors = CardDefaults.cardColors(containerColor = Surface),
        shape = RoundedCornerShape(12.dp)
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(16.dp),
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Icon(
                imageVector = item.icon,
                contentDescription = item.title,
                tint = Primary,
                modifier = Modifier.size(32.dp)
            )
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                item.title,
                color = Color.White,
                fontSize = 14.sp,
                fontWeight = FontWeight.Medium
            )
        }
    }
}

fun formatUptime(seconds: Double): String {
    val hours = (seconds / 3600).toInt()
    val minutes = ((seconds % 3600) / 60).toInt()
    return "${hours}h ${minutes}m"
}

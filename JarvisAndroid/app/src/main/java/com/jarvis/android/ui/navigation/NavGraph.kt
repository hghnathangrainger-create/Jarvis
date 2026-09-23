package com.jarvis.android.ui.navigation

import androidx.compose.runtime.Composable
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import com.jarvis.android.ui.screens.chat.ChatScreen
import com.jarvis.android.ui.screens.dashboard.DashboardScreen
import com.jarvis.android.ui.screens.goals.GoalsScreen
import com.jarvis.android.ui.screens.memory.MemoryScreen
import com.jarvis.android.ui.screens.settings.SettingsScreen

sealed class Screen(val route: String) {
    object Login : Screen("login")
    object Dashboard : Screen("dashboard")
    object Chat : Screen("chat")
    object Memory : Screen("memory")
    object Goals : Screen("goals")
    object Settings : Screen("settings")
}

@Composable
fun NavGraph(
    navController: NavHostController,
    startDestination: String = Screen.Login.route
) {
    NavHost(
        navController = navController,
        startDestination = startDestination
    ) {
        composable(Screen.Login.route) {
            com.jarvis.android.ui.screens.login.LoginScreen(
                onLoginSuccess = {
                    navController.navigate(Screen.Dashboard.route) {
                        popUpTo(Screen.Login.route) { inclusive = true }
                    }
                }
            )
        }

        composable(Screen.Dashboard.route) {
            DashboardScreen(
                onNavigate = { route -> navController.navigate(route) }
            )
        }

        composable(Screen.Chat.route) {
            ChatScreen()
        }

        composable(Screen.Memory.route) {
            MemoryScreen()
        }

        composable(Screen.Goals.route) {
            GoalsScreen()
        }

        composable(Screen.Settings.route) {
            SettingsScreen(
                onLogout = {
                    navController.navigate(Screen.Login.route) {
                        popUpTo(0) { inclusive = true }
                    }
                }
            )
        }
    }
}

package com.jarvis.android.ui.theme

import android.app.Activity
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalView
import androidx.core.view.WindowCompat

// Colors matching the web dashboard
val Background = Color(0xFF0A0A0F)
val JarvisSurface = Color(0xFF1A1A2E)
val SurfaceVariant = Color(0xFF252540)
val Primary = Color(0xFF00D4AA)
val PrimaryVariant = Color(0xFF00B894)
val Secondary = Color(0xFF6C5CE7)
val Error = Color(0xFFFF6B6B)
val OnBackground = Color.White
val OnSurface = Color.White
val OnSurfaceVariant = Color(0xFFB0B0B0)
val OnPrimary = Color.Black
val OnSecondary = Color.White


// Status colors
val StatusGreen = Color(0xFF00D4AA)
val StatusYellow = Color(0xFFFFD93D)
val StatusRed = Color(0xFFFF6B6B)

// Chat colors
val UserMessageBubble = Primary
val BotMessageBubble = SurfaceVariant
val UserMessageText = Color.Black
val BotMessageText = Color.White

private val DarkColorScheme = darkColorScheme(
    primary = Primary,
    secondary = Secondary,
    background = Background,
    surface = JarvisSurface,
    surfaceVariant = SurfaceVariant,
    error = Error,
    onPrimary = OnPrimary,
    onSecondary = OnSecondary,
    onBackground = OnBackground,
    onSurface = OnSurface,
    onSurfaceVariant = OnSurfaceVariant,
    onError = Color.White
)

@Composable
fun JarvisTheme(
    content: @Composable () -> Unit
) {
    val colorScheme = DarkColorScheme
    val view = LocalView.current

    if (!view.isInEditMode) {
        SideEffect {
            val window = (view.context as Activity).window
            window.statusBarColor = Background.toArgb()
            window.navigationBarColor = Background.toArgb()
            WindowCompat.getInsetsController(window, view).isAppearanceLightStatusBars = false
        }
    }

    MaterialTheme(
        colorScheme = colorScheme,
        content = content
    )
}

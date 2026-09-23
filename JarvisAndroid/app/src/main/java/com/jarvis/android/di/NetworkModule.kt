package com.jarvis.android.di

import android.content.Context
import com.jarvis.android.data.api.JarvisApi
import com.jarvis.android.data.api.WebSocketClient
import com.jarvis.android.data.repository.AuthRepository
import com.jarvis.android.data.repository.dataStore
import com.google.gson.Gson
import com.google.gson.GsonBuilder
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.runBlocking
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.concurrent.TimeUnit
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object NetworkModule {

    @Provides
    @Singleton
    fun provideGson(): Gson {
        return GsonBuilder()
            .setLenient()
            .create()
    }

    @Provides
    @Singleton
    fun provideAuthInterceptor(
        @ApplicationContext context: Context
    ): Interceptor {
        return Interceptor { chain ->
            val token = runBlocking {
                context.dataStore.data.map { preferences ->
                    preferences[AuthRepository.TOKEN_KEY]
                }.first()
            }
            val request = if (token != null) {
                chain.request().newBuilder()
                    .addHeader("Authorization", "Bearer $token")
                    .build()
            } else {
                chain.request()
            }
            chain.proceed(request)
        }
    }

    @Provides
    @Singleton
    fun provideOkHttpClient(
        authInterceptor: Interceptor
    ): OkHttpClient {
        val loggingInterceptor = HttpLoggingInterceptor().apply {
            level = HttpLoggingInterceptor.Level.BODY
        }

        return OkHttpClient.Builder()
            .addInterceptor(authInterceptor)
            .addInterceptor(loggingInterceptor)
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .writeTimeout(30, TimeUnit.SECONDS)
            .build()
    }

    @Provides
    @Singleton
    fun provideRetrofit(
        okHttpClient: OkHttpClient,
        gson: Gson,
        @ApplicationContext context: Context
    ): Retrofit {
        val baseUrl = runBlocking {
            context.dataStore.data.map { preferences ->
                preferences[AuthRepository.SERVER_URL_KEY]
                    ?: "http://10.0.2.2:8000"
            }.first()
        }

        return Retrofit.Builder()
            .baseUrl(if (baseUrl.endsWith("/")) baseUrl else "$baseUrl/")
            .client(okHttpClient)
            .addConverterFactory(GsonConverterFactory.create(gson))
            .build()
    }

    @Provides
    @Singleton
    fun provideJarvisApi(retrofit: Retrofit): JarvisApi {
        return retrofit.create(JarvisApi::class.java)
    }

    @Provides
    @Singleton
    fun provideWebSocketClient(
        okHttpClient: OkHttpClient,
        gson: Gson
    ): WebSocketClient {
        return WebSocketClient(okHttpClient, gson)
    }
}

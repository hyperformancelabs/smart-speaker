import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  View,
  Text,
  TextInput,
  Pressable,
  FlatList,
  ActivityIndicator,
  Alert,
  RefreshControl,
  ScrollView,
  Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useFocusEffect } from '@react-navigation/native';
import { Ionicons } from '@expo/vector-icons';
import { Timer, TimerAPI } from '../services/api';

function formatTime(totalSeconds: number): string {
  if (totalSeconds <= 0) return '00:00';
  const m = Math.floor(totalSeconds / 60).toString().padStart(2, '0');
  const s = (totalSeconds % 60).toString().padStart(2, '0');
  return `${m}:${s}`;
}

function getRemainingSeconds(timer: Timer): number {
  const startedAt = new Date(timer.started_at).getTime();
  const elapsedSeconds = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
  return Math.max(0, Number(timer.duration_seconds || 0) - elapsedSeconds);
}

export function TimersScreen() {
  const [timers, setTimers] = useState<Timer[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  // Countdown state
  const [countdownSeconds, setCountdownSeconds] = useState(0);
  const [countdownLabel, setCountdownLabel] = useState('');
  const [isRunning, setIsRunning] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Form state
  const [formMin, setFormMin] = useState('');
  const [formSec, setFormSec] = useState('');
  const [formLabel, setFormLabel] = useState('');

  const fetchTimers = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    try {
      const data = await TimerAPI.getAll();
      setTimers(data);
    } catch {
      // keep existing
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      fetchTimers();
    }, [fetchTimers]),
  );

  // Cleanup interval on unmount
  useEffect(() => {
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, []);

  const setQuickTime = (minutes: number) => {
    setFormMin(String(minutes));
    setFormSec('0');
  };

  const startNewTimer = async () => {
    const min = parseInt(formMin || '0');
    const sec = parseInt(formSec || '0');
    const totalSec = min * 60 + sec;
    const lbl = formLabel.trim();

    if (totalSec <= 0) {
      Alert.alert('Lỗi', 'Vui lòng thiết lập thời gian!');
      return;
    }

    // Save to API in background
    TimerAPI.create({ label: lbl || 'Timer', duration_seconds: totalSec })
      .then(() => fetchTimers())
      .catch(console.error);

    // Clear form
    setFormMin('');
    setFormSec('');
    setFormLabel('');

    // Clear old interval
    if (intervalRef.current) clearInterval(intervalRef.current);

    // Start countdown
    setCountdownSeconds(totalSec);
    setCountdownLabel(lbl || 'Timer');
    setIsRunning(true);

    let remaining = totalSec;
    intervalRef.current = setInterval(() => {
      remaining--;
      if (remaining <= 0) {
        setCountdownSeconds(0);
        setIsRunning(false);
        if (intervalRef.current) {
          clearInterval(intervalRef.current);
          intervalRef.current = null;
        }
        Alert.alert('⏰', 'Hẹn giờ đã kết thúc!');
        return;
      }
      setCountdownSeconds(remaining);
    }, 1000);
  };

  const cancelTimer = async (timerId: string) => {
    try {
      await TimerAPI.delete(timerId);
      fetchTimers();
    } catch (e: any) {
      Alert.alert('Lỗi', e.message || 'Không thể huỷ timer.');
    }
  };

  const restartFromHistory = (durationSeconds: number, label: string) => {
    setFormMin(String(Math.floor(durationSeconds / 60)));
    setFormSec(String(durationSeconds % 60));
    setFormLabel(label);
    // Auto start after a short delay to let state update
    setTimeout(() => startNewTimer(), 100);
  };

  if (loading) {
    return (
      <SafeAreaView edges={['top']} className="flex-1 items-center justify-center bg-[#f4efe6] font-sans">
        <ActivityIndicator size="large" color="#145374" />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView edges={['top']} className="flex-1 bg-[#f4efe6] font-sans">
      <ScrollView
        className="flex-1"
        contentContainerClassName="p-4 pb-8"
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => fetchTimers(true)} />}
      >
        {/* Section Title */}
        <Text className="mb-3 text-xs font-semibold uppercase tracking-widest text-[#5b6773]">
          Timer
        </Text>

        {/* Quick time buttons */}
        <View className="mb-4 flex-row gap-3">
          {[5, 10, 25, 60].map((min) => (
            <Pressable
              key={min}
              className="flex-1 items-center border border-[#e0d8d0] bg-[#fcf9f3] py-3"
              onPress={() => setQuickTime(min)}
            >
              <Text className="font-medium text-[#1f2933]">
                {min < 60 ? `${min} min` : '1 hr'}
              </Text>
            </Pressable>
          ))}
        </View>

        {/* Form */}
        <View className="mb-8 flex-row flex-wrap gap-3">
          <TextInput
            className="w-[70px] border border-[#e0d8d0] bg-[#fcf9f3] px-3 py-3 text-center text-[#1f2933]"
            placeholder="Min"
            placeholderTextColor="#5b6773"
            value={formMin}
            onChangeText={setFormMin}
            keyboardType="number-pad"
          />
          <TextInput
            className="w-[70px] border border-[#e0d8d0] bg-[#fcf9f3] px-3 py-3 text-center text-[#1f2933]"
            placeholder="Sec"
            placeholderTextColor="#5b6773"
            value={formSec}
            onChangeText={setFormSec}
            keyboardType="number-pad"
          />
          <TextInput
            className="min-w-[120px] flex-1 border border-[#e0d8d0] bg-[#fcf9f3] px-3 py-3 text-[#1f2933]"
            placeholder="Label (optional)"
            placeholderTextColor="#5b6773"
            value={formLabel}
            onChangeText={setFormLabel}
          />
          <Pressable
            className="items-center justify-center border border-[#1f7a58] px-5 py-3"
            onPress={startNewTimer}
          >
            <Text className="font-semibold text-[#1f7a58]">Start</Text>
          </Pressable>
        </View>

        {/* Countdown Display */}
        <View className="mb-10 items-center">
          <Text
            className={`text-7xl font-bold ${
              countdownSeconds <= 0 && isRunning === false && countdownLabel
                ? 'text-[#a43f24]'
                : 'text-[#1f2933]'
            }`}
            style={{ fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace' }}
          >
            {formatTime(countdownSeconds)}
          </Text>
          <Text className="mt-3 text-lg text-[#5b6773]">{countdownLabel || '-'}</Text>
        </View>

        {/* History */}
        <Text className="mb-3 text-xs font-semibold uppercase tracking-widest text-[#5b6773]">
          Bộ đếm đang chạy
        </Text>

        {timers.length === 0 ? (
          <Text className="py-6 text-center text-[#5b6773]">Chưa có lịch sử hẹn giờ.</Text>
        ) : (
          [...timers]
            .sort((a, b) => new Date(b.started_at).getTime() - new Date(a.started_at).getTime())
            .map((t) => (
              <View
                key={t.timer_id}
                className="flex-row items-center justify-between border-b border-b-[#e0d8d0] py-3"
              >
                <Text className="flex-1 text-base font-semibold text-[#1f2933]">
                  {t.label || 'Timer'}
                </Text>
                <Text className="mr-3 text-base text-[#5b6773]">
                  {formatTime(getRemainingSeconds(t))}
                </Text>
                <View className="flex-row gap-1">
                  <Pressable
                    className="p-2"
                    onPress={() => restartFromHistory(t.duration_seconds, t.label)}
                  >
                    <Ionicons name="refresh" size={18} color="#5b6773" />
                  </Pressable>
                  <Pressable className="p-2" onPress={() => cancelTimer(t.timer_id)}>
                    <Ionicons name="trash-outline" size={18} color="#a43f24" />
                  </Pressable>
                </View>
              </View>
            ))
        )}
      </ScrollView>
    </SafeAreaView>
  );
}


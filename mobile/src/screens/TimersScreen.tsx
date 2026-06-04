import React, { useCallback, useState } from 'react';
import { View, Text, FlatList, ActivityIndicator, RefreshControl } from 'react-native';
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

  const fetchTimers = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    try {
      const data = await TimerAPI.getAll();
      setTimers(data);
    } catch {
      // keep existing items
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

  if (loading) {
    return (
      <SafeAreaView edges={['top']} className="flex-1 items-center justify-center bg-[#f4efe6] font-sans">
        <ActivityIndicator size="large" color="#145374" />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView edges={['top']} className="flex-1 bg-[#f4efe6] font-sans">
      <View className="flex-1">
        <View className="px-4 pt-4 pb-2">
          <View className="flex-row items-center justify-between">
            <Text className="text-xl font-bold text-[#1f2933]">
              <Ionicons name="hourglass-outline" size={20} color="#1f2933" /> Hẹn giờ
            </Text>
            <Text className="rounded border border-[#e0d8d0] px-2 py-1 text-[10px] uppercase tracking-[1px] text-[#5b6773]">
              View only
            </Text>
          </View>
          <Text className="mt-2 text-sm text-[#5b6773]">
            Chỉ xem danh sách timer hiện có. Thao tác tạo, huỷ, chạy lại đã tắt.
          </Text>
        </View>

        {timers.length === 0 ? (
          <View className="flex-1 items-center justify-center p-8">
            <Ionicons name="hourglass-outline" size={48} color="#5b6773" />
            <Text className="mt-3 text-center text-[#5b6773]">
              Chưa có lịch sử hẹn giờ.
            </Text>
          </View>
        ) : (
          <FlatList
            data={timers}
            keyExtractor={(item) => item.timer_id}
            contentContainerClassName="px-4 pt-2 pb-8"
            refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => fetchTimers(true)} />}
            renderItem={({ item }) => (
              <View className="mb-3 flex-row items-center justify-between border border-[#e0d8d0] bg-[#fcf9f3] p-4">
                <View className="flex-1">
                  <Text className="text-base font-semibold text-[#1f2933]">
                    {item.label || 'Timer'}
                  </Text>
                  <Text className="mt-1 text-sm text-[#5b6773]">
                    Còn lại: {formatTime(getRemainingSeconds(item))}
                  </Text>
                </View>
                <View className="items-end">
                  <Text className="rounded border border-[#e0d8d0] px-2 py-1 text-[10px] uppercase tracking-[1px] text-[#5b6773]">
                    View only
                  </Text>
                  <Text className="mt-2 text-xs text-[#5b6773]">
                    {item.active ? 'Đang chạy' : 'Đã dừng'}
                  </Text>
                </View>
              </View>
            )}
          />
        )}
      </View>
    </SafeAreaView>
  );
}

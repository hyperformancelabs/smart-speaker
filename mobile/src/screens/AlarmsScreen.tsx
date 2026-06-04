import React, { useCallback, useState } from 'react';
import { View, Text, FlatList, ActivityIndicator, RefreshControl } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useFocusEffect } from '@react-navigation/native';
import { Ionicons } from '@expo/vector-icons';
import { Alarm, AlarmAPI } from '../services/api';

function formatAlarmTime(alarm: Alarm): string {
  if (alarm.schedule_type === 'datetime' && alarm.scheduled_for) {
    return new Date(alarm.scheduled_for).toLocaleString('vi-VN', {
      hour: '2-digit',
      minute: '2-digit',
      day: '2-digit',
      month: '2-digit',
    });
  }
  if (alarm.schedule_type === 'relative' && Number.isFinite(alarm.offset_seconds)) {
    return `+${alarm.offset_seconds}s`;
  }
  return alarm.time ? alarm.time.substring(0, 5) : '--:--';
}

function repeatLabel(repeat: string): string {
  if (repeat === 'daily') return 'Hàng ngày';
  if (repeat === 'weekly') return 'Hàng tuần';
  return '1 lần';
}

export function AlarmsScreen() {
  const [alarms, setAlarms] = useState<Alarm[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const fetchAlarms = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    try {
      const data = await AlarmAPI.getAll();
      setAlarms(data);
    } catch {
      // keep existing items
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      fetchAlarms();
    }, [fetchAlarms]),
  );

  if (loading) {
    return (
      <SafeAreaView edges={['top']} className="flex-1 items-center justify-center bg-[#f4efe6] font-sans">
        <ActivityIndicator size="large" color="#145374" />
        <Text className="mt-3 text-[#5b6773]">Đang tải dữ liệu...</Text>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView edges={['top']} className="flex-1 bg-[#f4efe6] font-sans">
      <View className="flex-1">
        <View className="px-4 pt-4 pb-2">
          <View className="flex-row items-center justify-between">
            <Text className="text-xl font-bold text-[#1f2933]">
              <Ionicons name="time-outline" size={20} color="#1f2933" /> Quản lý Báo thức
            </Text>
            <Text className="rounded border border-[#e0d8d0] px-2 py-1 text-[10px] uppercase tracking-[1px] text-[#5b6773]">
              View only
            </Text>
          </View>
          <Text className="mt-2 text-sm text-[#5b6773]">
            Chỉ xem danh sách báo thức hiện có. Thao tác tạo, sửa, xoá đã tắt.
          </Text>
        </View>

        {alarms.length === 0 ? (
          <View className="flex-1 items-center justify-center p-8">
            <Ionicons name="notifications-off-outline" size={48} color="#5b6773" />
            <Text className="mt-3 text-center text-[#5b6773]">
              Chưa có báo thức nào được thiết lập.
            </Text>
          </View>
        ) : (
          <FlatList
            data={alarms}
            keyExtractor={(item) => item.alarm_id}
            contentContainerClassName="px-4 pt-2 pb-8"
            refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => fetchAlarms(true)} />}
            renderItem={({ item }) => (
              <View
                className={`mb-3 flex-row items-center justify-between border bg-[#fcf9f3] p-4 ${
                  item.enabled ? 'border-[#145374]' : 'border-[#e0d8d0]'
                }`}
              >
                <View className="flex-1">
                  <Text
                    className={`text-3xl font-bold ${
                      item.enabled ? 'text-[#145374]' : 'text-[#1f2933]'
                    }`}
                  >
                    {formatAlarmTime(item)}
                  </Text>
                  <Text className="mt-1 text-sm text-[#5b6773]">
                    {item.label} - {repeatLabel(item.repeat)}
                  </Text>
                </View>
                <View className="items-end">
                  <Text className="rounded border border-[#e0d8d0] px-2 py-1 text-[10px] uppercase tracking-[1px] text-[#5b6773]">
                    View only
                  </Text>
                  <Text className="mt-2 text-xs text-[#5b6773]">
                    {item.enabled ? 'Đang bật' : 'Đang tắt'}
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

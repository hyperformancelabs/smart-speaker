import { Ionicons } from '@expo/vector-icons';
import { useFocusEffect } from '@react-navigation/native';
import React, { useCallback, useState } from 'react';
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { StatCard } from '../components/StatCard';
import { useAuth } from '../contexts/AuthContext';
import { AlarmAPI, ListAPI, MediaAPI, ProfileAPI, TimerAPI } from '../services/api';

export function OverviewScreen({ navigation }: any) {
  const { displayName, userName } = useAuth();
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [stats, setStats] = useState<any>({
    profileName: '',
    activeAlarms: 0,
    activeTimers: 0,
    totalNotes: 0,
    totalMedia: 0,
    nextAlarm: null,
    activeTimer: null,
    topNotes: [],
    recentMedia: null,
  });

  const getGreeting = () => {
    const hour = new Date().getHours();
    if (hour < 12) return 'Chào buổi sáng ☀️';
    if (hour < 18) return 'Chào buổi chiều ☕';
    return 'Chào buổi tối 🌙';
  };

  const formatTimeFromSeconds = (totalSeconds: number): string => {
    if (!totalSeconds || totalSeconds <= 0) return '00:00';
    const m = Math.floor(totalSeconds / 60)
      .toString()
      .padStart(2, '0');
    const s = (totalSeconds % 60).toString().padStart(2, '0');
    return `${m}:${s}`;
  };

  const getRemainingTimer = (timer: any) => {
    if (!timer) return '00:00';
    const startedAt = new Date(timer.started_at).getTime();
    const elapsedSeconds = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
    const rem = Math.max(0, Number(timer.duration_seconds || 0) - elapsedSeconds);
    return formatTimeFromSeconds(rem);
  };

  const fetchData = useCallback(
    async (isRefresh = false) => {
      if (isRefresh) setRefreshing(true);
      try {
        const [profile, alarms, timers, lists, media] = await Promise.all([
          ProfileAPI.get().catch(() => ({ name: '', user_name: '' }) as any),
          AlarmAPI.getAll().catch(() => []),
          TimerAPI.getAll().catch(() => []),
          ListAPI.getAll().catch(() => []),
          MediaAPI.getAll().catch(() => []),
        ]);

        const enabledAlarms = alarms.filter((a) => a.enabled);
        const nextAlarm = enabledAlarms
          .filter((a) => a.time)
          .sort((a, b) => a.time!.localeCompare(b.time!))[0];

        const activeTimersList = timers.filter((t) => t.active);
        const activeTimer = activeTimersList.length > 0 ? activeTimersList[0] : null;

        const uncompletedNotes: any[] = [];
        lists.forEach((list) => {
          list.items?.forEach((item) => {
            if (!item.completed) uncompletedNotes.push({ ...item, listName: list.list_name });
          });
        });

        const recentMedia = media.length > 0 ? media[0] : null;

        setStats({
          profileName: profile.name || profile.user_name || displayName || userName || 'Người dùng',
          activeAlarms: enabledAlarms.length,
          activeTimers: activeTimersList.length,
          totalNotes: uncompletedNotes.length,
          totalMedia: media.length,
          nextAlarm,
          activeTimer,
          topNotes: uncompletedNotes.slice(0, 3),
          recentMedia,
        });
      } catch {
        // keep existing stats
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [displayName, userName]
  );

  useFocusEffect(
    useCallback(() => {
      fetchData();
    }, [fetchData])
  );

  if (loading) {
    return (
      <SafeAreaView
        edges={['top']}
        className="flex-1 items-center justify-center bg-[#f4efe6] font-sans">
        <ActivityIndicator size="large" color="#145374" />
        <Text className="mt-3 text-[#5b6773]">Đang tải dữ liệu tổng quan...</Text>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView edges={['top']} className="flex-1 bg-[#f4efe6] font-sans">
      <ScrollView
        className="flex-1"
        contentContainerClassName="p-4 pb-8 gap-5"
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={() => fetchData(true)} />
        }>
        {/* Hero Section */}
        <View className="px-1 py-2">
          <Text className="mb-2 text-center text-2xl font-extrabold uppercase tracking-wider text-[#5b6773]">
            Smart Speaker
          </Text>
          <Text className="mt-1 font-bold text-xl text-[#145374]">
            {getGreeting()}, {stats.profileName}
          </Text>
        </View>

        {/* Actionable Cards */}
        <View className="gap-4">
          {/* Next Alarm & Timer row */}
          <View className="flex-row gap-4">
            <Pressable
              className="flex-1 rounded-2xl border border-[#e0d8d0] bg-[#fcf9f3] p-4 active:opacity-70"
              onPress={() => navigation.navigate('Báo thức')}>
              <View className="mb-2 flex-row items-center gap-2">
                <Ionicons name="alarm-outline" size={20} color="#145374" />
                <Text className="font-semibold text-[#5b6773]">Báo thức tới</Text>
              </View>
              {stats.nextAlarm ? (
                <>
                  <Text className="font-bold text-xl text-[#1f2933]">
                    {stats.nextAlarm.time ? stats.nextAlarm.time.substring(0, 5) : '--:--'}
                  </Text>
                  <Text className="mt-1 text-xs text-[#5b6773]" numberOfLines={1}>
                    {stats.nextAlarm.label || 'Không có nhãn'}
                  </Text>
                </>
              ) : (
                <Text className="mt-1 text-sm text-[#5b6773]">Không có</Text>
              )}
            </Pressable>

            <Pressable
              className="flex-1 rounded-2xl border border-[#e0d8d0] bg-[#fcf9f3] p-4 active:opacity-70"
              onPress={() => navigation.navigate('Hẹn giờ')}>
              <View className="mb-2 flex-row items-center gap-2">
                <Ionicons name="hourglass-outline" size={20} color="#0d3c52" />
                <Text className="font-semibold text-[#5b6773]">Hẹn giờ</Text>
              </View>
              {stats.activeTimer ? (
                <>
                  <Text className="font-bold text-xl text-[#1f2933]">
                    {getRemainingTimer(stats.activeTimer)}
                  </Text>
                  <Text className="mt-1 text-xs text-[#5b6773]" numberOfLines={1}>
                    {stats.activeTimer.label || 'Đang đếm'}
                  </Text>
                </>
              ) : (
                <Text className="mt-1 text-sm text-[#5b6773]">Không chạy</Text>
              )}
            </Pressable>
          </View>

          {/* To-Do Preview */}
          <Pressable
            className="rounded-2xl border border-[#e0d8d0] bg-[#fcf9f3] p-4 active:opacity-70"
            onPress={() => navigation.navigate('Ghi chú')}>
            <View className="mb-3 flex-row items-center justify-between">
              <View className="flex-row items-center gap-2">
                <Ionicons name="checkbox-outline" size={20} color="#1f7a58" />
                <Text className="font-semibold text-[#5b6773]">Việc cần làm</Text>
              </View>
              <View className="rounded-full bg-[#1f7a58] px-2 py-0.5">
                <Text className="font-bold text-xs text-white">{stats.totalNotes}</Text>
              </View>
            </View>

            {stats.topNotes.length > 0 ? (
              <View className="gap-2">
                {stats.topNotes.map((note: any, idx: number) => (
                  <View key={note.item_id || idx} className="flex-row items-center gap-2">
                    <Ionicons name="ellipse-outline" size={12} color="#a43f24" />
                    <Text className="flex-1 text-sm text-[#1f2933]" numberOfLines={1}>
                      {note.content}
                    </Text>
                  </View>
                ))}
              </View>
            ) : (
              <Text className="text-sm text-[#5b6773]">
                Tuyệt vời! Bạn đã hoàn thành hết công việc.
              </Text>
            )}
          </Pressable>

          {/* Recent Media */}
          <Pressable
            className="rounded-2xl border border-[#e0d8d0] bg-[#fcf9f3] p-4 active:opacity-70"
            onPress={() => navigation.navigate('Cá nhân', { screen: 'MediaHistory' })}>
            <View className="mb-1 flex-row items-center justify-between">
              <View className="flex-row items-center gap-2">
                <Ionicons name="musical-notes-outline" size={20} color="#a43f24" />
                <Text className="font-semibold text-[#5b6773]">Nghe gần đây</Text>
              </View>
            </View>
            {stats.recentMedia ? (
              <View className="mt-2 flex-row items-center gap-3">
                <View className="h-10 w-10 items-center justify-center rounded-full bg-[#e6ecef]">
                  <Ionicons name="play" size={18} color="#145374" />
                </View>
                <View className="flex-1">
                  <Text className="font-bold text-[#1f2933]" numberOfLines={1}>
                    {stats.recentMedia.title}
                  </Text>
                  <Text className="mt-0.5 text-xs text-[#5b6773]">
                    {stats.recentMedia.source || 'Nguồn không xác định'}
                  </Text>
                </View>
              </View>
            ) : (
              <Text className="mt-1 text-sm text-[#5b6773]">Chưa có lịch sử nghe nhạc.</Text>
            )}
          </Pressable>
        </View>

        {/* Stats Grid (Quick Summary) */}
        <View className="mt-2">
          <Text className="mb-3 ml-1 font-semibold text-xs uppercase tracking-widest text-[#5b6773]">
            TỔNG QUAN HỆ THỐNG
          </Text>
          <View className="flex-row flex-wrap gap-3">
            <StatCard
              icon="time"
              value={stats.activeAlarms}
              label="Báo thức"
              iconColor="#145374"
              onPress={() => navigation.navigate('Báo thức')}
            />
            <StatCard
              icon="hourglass"
              value={stats.activeTimers}
              label="Hẹn giờ"
              iconColor="#0d3c52"
              onPress={() => navigation.navigate('Hẹn giờ')}
            />
            <StatCard
              icon="document-text"
              value={stats.totalNotes}
              label="Ghi chú"
              iconColor="#1f7a58"
              onPress={() => navigation.navigate('Ghi chú')}
            />
            <StatCard
              icon="play-circle"
              value={stats.totalMedia}
              label="Media history"
              iconColor="#a43f24"
              onPress={() => navigation.navigate('Cá nhân', { screen: 'MediaHistory' })}
            />
          </View>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

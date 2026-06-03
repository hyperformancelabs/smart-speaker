import React, { useCallback, useState } from 'react';
import {
  View,
  Text,
  FlatList,
  Pressable,
  ActivityIndicator,
  Linking,
  RefreshControl,
} from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import { Ionicons } from '@expo/vector-icons';
import { MediaItem, MediaAPI } from '../services/api';
import { ConfirmModal } from '../components/ConfirmModal';

function formatRelativeTime(isoString: string): string {
  if (!isoString) return '';
  const date = new Date(isoString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return 'Vừa xong';
  if (diffMin < 60) return `${diffMin} phút trước`;
  const diffHour = Math.floor(diffMin / 60);
  if (diffHour < 24) return `${diffHour} giờ trước`;
  const diffDay = Math.floor(diffHour / 24);
  if (diffDay < 7) return `${diffDay} ngày trước`;
  return date.toLocaleDateString('vi-VN', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  });
}

export function MediaScreen() {
  const [items, setItems] = useState<MediaItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  const fetchMedia = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    try {
      const data = await MediaAPI.getAll();
      setItems(data);
    } catch {
      // keep
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      fetchMedia();
    }, [fetchMedia]),
  );

  const handleDelete = async () => {
    if (!deleteTarget) return;
    try {
      await MediaAPI.delete(deleteTarget);
      setDeleteTarget(null);
      fetchMedia();
    } catch {
      setDeleteTarget(null);
    }
  };

  if (loading) {
    return (
      <View className="flex-1 items-center justify-center bg-[#f4efe6]">
        <ActivityIndicator size="large" color="#145374" />
        <Text className="mt-3 text-[#5b6773]">Đang tải lịch sử media...</Text>
      </View>
    );
  }

  const renderItem = ({ item }: { item: MediaItem }) => (
    <View className="flex-row items-center justify-between border-b border-b-[#e0d8d0] px-4 py-3">
      <View className="flex-1 mr-3">
        <Text className="text-base font-medium text-[#1f2933]" numberOfLines={1}>
          {item.title || 'Unknown'}
        </Text>
        <View className="mt-1 flex-row items-center gap-2">
          {item.source ? (
            <View className="bg-red-500/10 px-2 py-0.5 rounded-full">
              <Text className="text-xs font-semibold text-red-500">{item.source}</Text>
            </View>
          ) : null}
          <Text className="text-xs text-[#5b6773]">
            {formatRelativeTime(item.last_played_at)}
          </Text>
        </View>
      </View>
      <View className="flex-row gap-1">
        <Pressable
          className="p-2"
          onPress={() => {
            if (item.public_stream_url) Linking.openURL(item.public_stream_url);
          }}
        >
          <Ionicons name="play" size={18} color="#145374" />
        </Pressable>
        <Pressable className="p-2" onPress={() => setDeleteTarget(item.media_id)}>
          <Ionicons name="trash-outline" size={18} color="#a43f24" />
        </Pressable>
      </View>
    </View>
  );

  return (
    <View className="flex-1 bg-[#f4efe6]">
      {/* Header */}
      <View className="px-4 pt-4 pb-2">
        <Text className="text-xl font-bold text-[#1f2933]">
          <Ionicons name="time-outline" size={20} color="#145374" /> Media History
        </Text>
      </View>

      {items.length === 0 ? (
        <View className="flex-1 items-center justify-center">
          <Ionicons name="musical-notes-outline" size={48} color="#5b6773" />
          <Text className="mt-3 text-[#5b6773]">Chưa có media nào được phát.</Text>
        </View>
      ) : (
        <FlatList
          data={items}
          keyExtractor={(item) => item.media_id}
          renderItem={renderItem}
          className="border border-[#e0d8d0] bg-[#fcf9f3] mx-4"
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={() => fetchMedia(true)} />
          }
        />
      )}

      <ConfirmModal
        visible={deleteTarget !== null}
        message="Xóa mục này khỏi lịch sử media?"
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </View>
  );
}

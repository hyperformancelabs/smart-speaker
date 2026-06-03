import React, { useCallback, useState } from 'react';
import {
  View,
  Text,
  FlatList,
  Pressable,
  Switch,
  Modal,
  TextInput,
  ActivityIndicator,
  Alert,
  RefreshControl,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useFocusEffect } from '@react-navigation/native';
import { Ionicons } from '@expo/vector-icons';
import { Alarm, AlarmAPI } from '../services/api';
import { ConfirmModal } from '../components/ConfirmModal';

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

  // Modal state
  const [modalVisible, setModalVisible] = useState(false);
  const [editId, setEditId] = useState('');
  const [timeHour, setTimeHour] = useState('07');
  const [timeMin, setTimeMin] = useState('00');
  const [label, setLabel] = useState('');
  const [repeat, setRepeat] = useState<'once' | 'daily'>('once');

  // Confirm delete
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  const fetchAlarms = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    try {
      const data = await AlarmAPI.getAll();
      setAlarms(data);
    } catch {
      // keep existing
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

  const handleToggle = async (alarm: Alarm, enabled: boolean) => {
    // Optimistic update
    setAlarms((prev) =>
      prev.map((a) => (a.alarm_id === alarm.alarm_id ? { ...a, enabled } : a)),
    );
    try {
      await AlarmAPI.updateStatus(alarm.alarm_id, enabled);
    } catch {
      // Revert
      setAlarms((prev) =>
        prev.map((a) => (a.alarm_id === alarm.alarm_id ? { ...a, enabled: !enabled } : a)),
      );
      Alert.alert('Lỗi', 'Không thể cập nhật trạng thái báo thức.');
    }
  };

  const openModal = (alarm?: Alarm) => {
    if (alarm) {
      if (alarm.schedule_type && alarm.schedule_type !== 'time') {
        Alert.alert('Thông báo', 'Chỉ hỗ trợ chỉnh báo thức giờ cố định.');
        return;
      }
      setEditId(alarm.alarm_id);
      const t = alarm.time?.substring(0, 5) || '07:00';
      setTimeHour(t.split(':')[0]);
      setTimeMin(t.split(':')[1]);
      setLabel(alarm.label || '');
      setRepeat((alarm.repeat as 'once' | 'daily') || 'once');
    } else {
      setEditId('');
      setTimeHour('07');
      setTimeMin('00');
      setLabel('');
      setRepeat('once');
    }
    setModalVisible(true);
  };

  const handleSave = async () => {
    const h = timeHour.padStart(2, '0');
    const m = timeMin.padStart(2, '0');
    const payload = {
      schedule_type: 'time',
      time: `${h}:${m}`,
      label: label.trim() || 'Báo thức',
      repeat,
    };

    try {
      if (editId) {
        await AlarmAPI.update(editId, payload);
      } else {
        await AlarmAPI.create(payload);
      }
      setModalVisible(false);
      fetchAlarms();
    } catch (e: any) {
      Alert.alert('Lỗi', e.message || 'Không thể lưu báo thức.');
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    try {
      await AlarmAPI.delete(deleteTarget);
      setDeleteTarget(null);
      fetchAlarms();
    } catch {
      Alert.alert('Lỗi', 'Không thể xóa báo thức.');
      setDeleteTarget(null);
    }
  };

  if (loading) {
    return (
      <SafeAreaView edges={['top']} className="flex-1 items-center justify-center bg-[#f4efe6] font-sans">
        <ActivityIndicator size="large" color="#145374" />
        <Text className="mt-3 text-[#5b6773]">Đang tải dữ liệu...</Text>
      </SafeAreaView>
    );
  }

  const renderAlarm = ({ item }: { item: Alarm }) => {
    const canEdit = (item.schedule_type || 'time') === 'time';
    return (
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
        <View className="flex-row items-center gap-3">
          <Switch
            value={item.enabled}
            onValueChange={(val) => handleToggle(item, val)}
            trackColor={{ false: '#e9ecef', true: '#145374' }}
            thumbColor="white"
          />
          <Pressable
            onPress={() => openModal(item)}
            disabled={!canEdit}
            className="p-2"
          >
            <Ionicons
              name="pencil"
              size={18}
              color={canEdit ? '#5b6773' : '#ced4da'}
            />
          </Pressable>
          <Pressable onPress={() => setDeleteTarget(item.alarm_id)} className="p-2">
            <Ionicons name="trash-outline" size={18} color="#a43f24" />
          </Pressable>
        </View>
      </View>
    );
  };

  return (
    <SafeAreaView edges={['top']} className="flex-1 bg-[#f4efe6] font-sans">
      <View className="flex-1">
        {/* Header */}
        <View className="flex-row items-center justify-between px-4 pt-4 pb-2">
          <Text className="text-xl font-bold text-[#1f2933]">
            <Ionicons name="time-outline" size={20} color="#1f2933" /> Quản lý Báo thức
          </Text>
          <Pressable
            className="flex-row items-center gap-1 bg-[#145374] px-4 py-2"
            onPress={() => openModal()}
          >
            <Ionicons name="add" size={18} color="white" />
            <Text className="font-semibold text-white">Thêm mới</Text>
          </Pressable>
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
            renderItem={renderAlarm}
            contentContainerClassName="px-4 pt-2 pb-8"
            refreshControl={
              <RefreshControl refreshing={refreshing} onRefresh={() => fetchAlarms(true)} />
            }
          />
        )}

        {/* Add/Edit Modal */}
        <Modal
          transparent
          animationType="fade"
          visible={modalVisible}
          onRequestClose={() => setModalVisible(false)}
        >
          <Pressable
            className="flex-1 items-center justify-center bg-black/40"
            onPress={() => setModalVisible(false)}
          >
            <Pressable
              className="mx-6 w-[90%] max-w-[400px] border border-[#e0d8d0] bg-[#fcf9f3] p-6"
              onPress={() => {}}
            >
              <Text className="mb-4 text-xl font-bold text-[#1f2933]">
                {editId ? 'Chỉnh sửa Báo thức' : 'Thêm Báo thức'}
              </Text>

              <View className="gap-4">
                {/* Time inputs */}
                <View className="gap-1">
                  <Text className="text-sm font-medium text-[#1f2933]">Giờ (HH:mm)</Text>
                  <View className="flex-row items-center gap-2">
                    <TextInput
                      className="flex-1 border border-[#e0d8d0] bg-[#fcf9f3] px-4 py-3 text-center text-lg text-[#1f2933]"
                      placeholder="HH"
                      placeholderTextColor="#5b6773"
                      value={timeHour}
                      onChangeText={setTimeHour}
                      keyboardType="number-pad"
                      maxLength={2}
                    />
                    <Text className="text-2xl font-bold text-[#1f2933]">:</Text>
                    <TextInput
                      className="flex-1 border border-[#e0d8d0] bg-[#fcf9f3] px-4 py-3 text-center text-lg text-[#1f2933]"
                      placeholder="mm"
                      placeholderTextColor="#5b6773"
                      value={timeMin}
                      onChangeText={setTimeMin}
                      keyboardType="number-pad"
                      maxLength={2}
                    />
                  </View>
                </View>

                {/* Label */}
                <View className="gap-1">
                  <Text className="text-sm font-medium text-[#1f2933]">Nhãn báo thức</Text>
                  <TextInput
                    className="border border-[#e0d8d0] bg-[#fcf9f3] px-4 py-3 text-base text-[#1f2933]"
                    placeholder="Ví dụ: Thức dậy"
                    placeholderTextColor="#5b6773"
                    value={label}
                    onChangeText={setLabel}
                  />
                </View>

                {/* Repeat */}
                <View className="gap-1">
                  <Text className="text-sm font-medium text-[#1f2933]">Lặp lại</Text>
                  <View className="flex-row gap-2">
                    <Pressable
                      className={`flex-1 items-center border py-3 ${
                        repeat === 'once'
                          ? 'border-[#145374] bg-[#e6ecef]'
                          : 'border-[#e0d8d0] bg-[#fcf9f3]'
                      }`}
                      onPress={() => setRepeat('once')}
                    >
                      <Text
                        className={`font-medium ${
                          repeat === 'once' ? 'text-[#145374]' : 'text-[#1f2933]'
                        }`}
                      >
                        Chỉ một lần
                      </Text>
                    </Pressable>
                    <Pressable
                      className={`flex-1 items-center border py-3 ${
                        repeat === 'daily'
                          ? 'border-[#145374] bg-[#e6ecef]'
                          : 'border-[#e0d8d0] bg-[#fcf9f3]'
                      }`}
                      onPress={() => setRepeat('daily')}
                    >
                      <Text
                        className={`font-medium ${
                          repeat === 'daily' ? 'text-[#145374]' : 'text-[#1f2933]'
                        }`}
                      >
                        Hàng ngày
                      </Text>
                    </Pressable>
                  </View>
                </View>

                {/* Actions */}
                <View className="mt-2 flex-row gap-3">
                  <Pressable
                    className="flex-1 items-center border border-[#e0d8d0] bg-[#f4efe6] py-3"
                    onPress={() => setModalVisible(false)}
                  >
                    <Text className="font-semibold text-[#1f2933]">Hủy</Text>
                  </Pressable>
                  <Pressable
                    className="flex-1 items-center bg-[#145374] py-3"
                    onPress={handleSave}
                  >
                    <Text className="font-semibold text-white">Lưu</Text>
                  </Pressable>
                </View>
              </View>
            </Pressable>
          </Pressable>
        </Modal>

        {/* Confirm Delete */}
        <ConfirmModal
          visible={deleteTarget !== null}
          message="Bạn có chắc chắn muốn xóa báo thức này?"
          onConfirm={handleDelete}
          onCancel={() => setDeleteTarget(null)}
        />
      </View>
    </SafeAreaView>
  );
}

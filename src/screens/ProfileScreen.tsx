import React, { useCallback, useState } from 'react';
import {
  View,
  Text,
  TextInput,
  Pressable,
  ScrollView,
  ActivityIndicator,
  Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useFocusEffect } from '@react-navigation/native';
import { Ionicons } from '@expo/vector-icons';
import { ProfileAPI, UserProfile } from '../services/api';
import { useAuth } from '../contexts/AuthContext';
import { ConfirmModal } from '../components/ConfirmModal';

export function ProfileScreen({ navigation }: any) {
  const { logout, updateProfile } = useAuth();
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const [name, setName] = useState('');
  const [userName, setUserName] = useState('');
  const [password, setPassword] = useState('');

  const [logoutConfirm, setLogoutConfirm] = useState(false);

  const fetchProfile = useCallback(async () => {
    try {
      const data = await ProfileAPI.get();
      setProfile(data);
      setName(data.name || '');
      setUserName(data.user_name || '');
    } catch {
      // keep empty
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      fetchProfile();
    }, [fetchProfile]),
  );

  const handleSave = async () => {
    setSaving(true);
    try {
      let updatedProfile = profile;

      if (name !== (profile?.name || '')) {
        updatedProfile = await ProfileAPI.updateField('name', name.trim());
      }
      if (userName !== (profile?.user_name || '')) {
        updatedProfile = await ProfileAPI.updateField('user_name', userName.trim());
      }
      if (password) {
        updatedProfile = await ProfileAPI.updateField('user_password', password);
        setPassword('');
      }

      if (updatedProfile) {
        setProfile(updatedProfile);
        await updateProfile(updatedProfile.name || '', updatedProfile.user_name || '');
      }

      Alert.alert('Thành công', 'Đã lưu thay đổi thành công!');
    } catch (err: any) {
      Alert.alert('Lỗi', 'Lỗi lưu thông tin: ' + err.message);
    } finally {
      setSaving(false);
    }
  };

  const handleLogout = async () => {
    setLogoutConfirm(false);
    await logout();
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
        keyboardShouldPersistTaps="handled"
      >
        {/* Header */}
        <View className="mb-4">
          <Text className="text-xl font-bold text-[#1f2933]">
            <Ionicons name="person-outline" size={20} color="#1f2933" /> Hồ sơ Cá nhân
          </Text>
        </View>

        <View className="border border-[#e0d8d0] bg-[#fcf9f3] p-6">
          {/* Avatar */}
          <View className="mb-5 items-center">
            <View className="mb-3 h-24 w-24 items-center justify-center rounded-full bg-[#145374]">
              <Ionicons name="person" size={48} color="white" />
            </View>
            <Text className="text-lg font-semibold text-[#1f2933]">Thông tin tài khoản</Text>
            <Text className="mt-1 text-sm text-[#5b6773]">
              NFC: {profile?.nfc_tag_id || '-'}
            </Text>
            <Text className="text-sm text-[#5b6773]">User ID: {profile?.user_id || '-'}</Text>
          </View>

          {/* Form */}
          <View className="gap-4">
            <View className="gap-1">
              <Text className="text-sm font-medium text-[#1f2933]">Họ và tên</Text>
              <TextInput
                className="border border-[#e0d8d0] bg-[#fcf9f3] px-4 py-3 text-base text-[#1f2933]"
                placeholder="Nhập tên của bạn"
                placeholderTextColor="#5b6773"
                value={name}
                onChangeText={setName}
              />
            </View>

            <View className="gap-1">
              <Text className="text-sm font-medium text-[#1f2933]">Username</Text>
              <TextInput
                className="border border-[#e0d8d0] bg-[#fcf9f3] px-4 py-3 text-base text-[#1f2933]"
                placeholder="Nhập username"
                placeholderTextColor="#5b6773"
                value={userName}
                onChangeText={setUserName}
                autoCapitalize="none"
                autoCorrect={false}
              />
            </View>

            <View className="gap-1">
              <Text className="text-sm font-medium text-[#1f2933]">Mật khẩu mới</Text>
              <TextInput
                className="border border-[#e0d8d0] bg-[#fcf9f3] px-4 py-3 text-base text-[#1f2933]"
                placeholder="Bỏ trống nếu không đổi"
                placeholderTextColor="#5b6773"
                value={password}
                onChangeText={setPassword}
                secureTextEntry
              />
            </View>

            <Pressable
              className="mt-2 flex-row items-center justify-center gap-2 bg-[#145374] px-6 py-3"
              onPress={handleSave}
              disabled={saving}
            >
              {saving ? (
                <ActivityIndicator size="small" color="white" />
              ) : (
                <>
                  <Ionicons name="save-outline" size={18} color="white" />
                  <Text className="text-base font-semibold text-white">Lưu thay đổi</Text>
                </>
              )}
            </Pressable>
          </View>
        </View>

        {/* Media History Link */}
        <Pressable
          className="mt-4 flex-row items-center justify-between border border-[#e0d8d0] bg-[#fcf9f3] px-4 py-4"
          onPress={() => navigation.navigate('MediaHistory')}
        >
          <View className="flex-row items-center gap-3">
            <Ionicons name="play-circle-outline" size={22} color="#a43f24" />
            <Text className="text-base font-medium text-[#1f2933]">Xem Media History</Text>
          </View>
          <Ionicons name="chevron-forward" size={18} color="#5b6773" />
        </Pressable>

        {/* Logout */}
        <Pressable
          className="mt-4 flex-row items-center justify-center gap-2 border border-[#a43f24] bg-[#fcf9f3] px-6 py-3"
          onPress={() => setLogoutConfirm(true)}
        >
          <Ionicons name="log-out-outline" size={18} color="#a43f24" />
          <Text className="text-base font-semibold text-[#a43f24]">Đăng xuất</Text>
        </Pressable>

        <ConfirmModal
          visible={logoutConfirm}
          message="Bạn có chắc chắn muốn đăng xuất tài khoản này không?"
          onConfirm={handleLogout}
          onCancel={() => setLogoutConfirm(false)}
        />
      </ScrollView>
    </SafeAreaView>
  );
}

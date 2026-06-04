import React, { useState } from 'react';
import {
  View,
  Text,
  TextInput,
  Pressable,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  ActivityIndicator,
  Image,
  ImageBackground,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useAuth } from '../contexts/AuthContext';
import { AuthAPI } from '../services/api';

export function LoginScreen({ navigation }: any) {
  const { login } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [usernameError, setUsernameError] = useState('');
  const [passwordError, setPasswordError] = useState('');
  const [formError, setFormError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleLogin = async () => {
    setUsernameError('');
    setPasswordError('');
    setFormError('');

    let hasError = false;
    if (!username.trim()) {
      setUsernameError('Vui lòng nhập tên đăng nhập.');
      hasError = true;
    }
    if (!password) {
      setPasswordError('Vui lòng nhập mật khẩu.');
      hasError = true;
    }
    if (hasError) return;

    setLoading(true);
    try {
      const user = await AuthAPI.login({
        user_name: username.trim(),
        user_password: password,
      });
      await login(user);
    } catch (error: any) {
      setFormError(error.message || 'Lỗi kết nối đến máy chủ. Vui lòng thử lại sau!');
    } finally {
      setLoading(false);
    }
  };

  const handleMockLogin = async () => {
    setUsernameError('');
    setPasswordError('');
    setFormError('');
    setLoading(true);
    try {
      await login({
        user_id: 'mock-user-id-123',
        nfc_tag_id: 'mock-nfc-tag-id-123',
        user_name: 'demo_user',
        name: 'Người dùng thử nghiệm',
      });
    } catch {
      setFormError('Lỗi đăng nhập thử nghiệm.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <ImageBackground
      source={require('../../assets/bg.jpg')}
      className="flex-1"
      resizeMode="cover"
    >
      <SafeAreaView edges={['top', 'bottom']} className="flex-1 bg-transparent font-sans">
        <KeyboardAvoidingView
          className="flex-1"
          behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        >
          <ScrollView
            contentContainerClassName="flex-grow items-center justify-center px-6 py-10"
            keyboardShouldPersistTaps="handled"
          >
            <View className="w-full max-w-[400px] border border-[#e0d8d0]/60 bg-[#fcf9f3]/95 p-6 rounded-2xl shadow-2xl">
              {/* Header */}
              <View className="mb-6 items-center">
                <Image
                  source={require('../../assets/logo.png')}
                  className="mb-3 h-16 w-16"
                  resizeMode="contain"
                />
                <Text className="mb-1 text-2xl font-bold text-[#1f2933]">Smart Speaker</Text>
                <Text className="text-center text-sm text-[#5b6773]">
                  Đăng nhập để quản lý báo thức, timer và danh sách của bạn
                </Text>
              </View>

              {/* Form */}
              <View className="gap-4">
                {/* Username */}
                <View className="gap-1">
                  <Text className="text-sm font-medium text-[#1f2933]">
                    <Ionicons name="person-outline" size={14} color="#1f2933" /> Tên đăng nhập
                  </Text>
                  <TextInput
                    className={`rounded-xl border bg-[#fcf9f3] px-4 py-3 text-base text-[#1f2933] ${
                      usernameError ? 'border-[#a43f24]' : 'border-[#e0d8d0]'
                    }`}
                    placeholder="Nhập username"
                    placeholderTextColor="#5b6773"
                    value={username}
                    onChangeText={setUsername}
                    autoCapitalize="none"
                    autoCorrect={false}
                  />
                  {usernameError ? (
                    <Text className="text-xs text-[#a43f24]">{usernameError}</Text>
                  ) : null}
                </View>

                {/* Password */}
                <View className="gap-1">
                  <Text className="text-sm font-medium text-[#1f2933]">
                    <Ionicons name="lock-closed" size={14} color="#1f2933" /> Mật khẩu
                  </Text>
                  <TextInput
                    className={`rounded-xl border bg-[#fcf9f3] px-4 py-3 text-base text-[#1f2933] ${
                      passwordError ? 'border-[#a43f24]' : 'border-[#e0d8d0]'
                    }`}
                    placeholder="Nhập mật khẩu"
                    placeholderTextColor="#5b6773"
                    value={password}
                    onChangeText={setPassword}
                    secureTextEntry
                  />
                  {passwordError ? (
                    <Text className="text-xs text-[#a43f24]">{passwordError}</Text>
                  ) : null}
                </View>

                {/* Form error */}
                {formError ? (
                  <Text className="text-center text-sm font-bold text-[#a43f24]">{formError}</Text>
                ) : null}

                {/* Submit */}
                <Pressable
                  className="mt-1 flex-row items-center justify-center gap-2 border border-[#e0d8d0] bg-[#f4efe6] px-6 py-3 rounded-xl"
                  onPress={handleLogin}
                  disabled={loading}
                >
                  {loading ? (
                    <ActivityIndicator size="small" color="#1f2933" />
                  ) : (
                    <Text className="text-base font-semibold text-[#1f2933]">Đăng nhập</Text>
                  )}
                </Pressable>

                {/* Mock Bypass Submit */}
                <Pressable
                  className="mt-2 flex-row items-center justify-center gap-2 border border-[#145374] bg-[#e6ecef] px-6 py-3 rounded-xl"
                  onPress={handleMockLogin}
                  disabled={loading}
                >
                  <Ionicons name="eye-outline" size={18} color="#145374" />
                  <Text className="text-base font-semibold text-[#145374]">Đăng nhập dùng thử (Mock)</Text>
                </Pressable>
              </View>

              {/* Footer — link to signup */}
              <View className="mt-6 items-center">
                <Text className="text-sm text-[#5b6773]">Chưa có tài khoản?</Text>
                <Pressable
                  className="mt-1 flex-row items-center gap-1"
                  onPress={() => navigation.navigate('Signup')}
                >
                  <Ionicons name="person-add-outline" size={14} color="#145374" />
                  <Text className="text-sm font-semibold text-[#145374]">Tạo tài khoản mới</Text>
                </Pressable>
              </View>
            </View>
          </ScrollView>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </ImageBackground>
  );
}

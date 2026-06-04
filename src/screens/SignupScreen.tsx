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
  Alert,
  Image,
  ImageBackground,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { SafeAreaView } from 'react-native-safe-area-context';
import { AuthAPI } from '../services/api';

export function SignupScreen({ navigation }: any) {
  const [nfcTagId, setNfcTagId] = useState('');
  const [name, setName] = useState('');
  const [userName, setUserName] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSignup = async () => {
    if (!nfcTagId.trim() || !name.trim() || !userName.trim() || !password) {
      Alert.alert('Lỗi', 'Vui lòng điền đầy đủ tất cả các trường.');
      return;
    }
    if (password.length < 6) {
      Alert.alert('Lỗi', 'Mật khẩu phải có ít nhất 6 ký tự.');
      return;
    }

    setLoading(true);
    try {
      await AuthAPI.signup({
        nfc_tag_id: nfcTagId.trim(),
        name: name.trim(),
        user_name: userName.trim(),
        user_password: password,
      });
      Alert.alert('Thành công', 'Đăng ký thành công! Vui lòng đăng nhập.', [
        { text: 'OK', onPress: () => navigation.goBack() },
      ]);
    } catch (error: any) {
      Alert.alert('Lỗi', error.message || 'Không thể hoàn tất đăng ký.');
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
                <Text className="mb-1 text-2xl font-bold text-[#1f2933]">Tạo Tài Khoản</Text>
                <Text className="text-sm text-[#1f7a58]">
                  <Ionicons name="wifi" size={14} color="#1f7a58" /> Đăng ký cho thẻ NFC
                </Text>
              </View>

              {/* Form */}
              <View className="gap-4">
                <View className="gap-1">
                  <Text className="text-sm font-medium text-[#1f2933]">Mã NFC</Text>
                  <TextInput
                    className="rounded-xl border border-[#e0d8d0] bg-[#fcf9f3] px-4 py-3 text-base text-[#1f2933]"
                    placeholder="Nhập mã thẻ NFC"
                    placeholderTextColor="#5b6773"
                    value={nfcTagId}
                    onChangeText={setNfcTagId}
                    autoCapitalize="none"
                  />
                </View>

                <View className="gap-1">
                  <Text className="text-sm font-medium text-[#1f2933]">Họ và tên</Text>
                  <TextInput
                    className="rounded-xl border border-[#e0d8d0] bg-[#fcf9f3] px-4 py-3 text-base text-[#1f2933]"
                    placeholder="Ví dụ: Nguyễn Văn A"
                    placeholderTextColor="#5b6773"
                    value={name}
                    onChangeText={setName}
                  />
                </View>

                <View className="gap-1">
                  <Text className="text-sm font-medium text-[#1f2933]">Username</Text>
                  <TextInput
                    className="rounded-xl border border-[#e0d8d0] bg-[#fcf9f3] px-4 py-3 text-base text-[#1f2933]"
                    placeholder="username"
                    placeholderTextColor="#5b6773"
                    value={userName}
                    onChangeText={setUserName}
                    autoCapitalize="none"
                    autoCorrect={false}
                  />
                </View>

                <View className="gap-1">
                  <Text className="text-sm font-medium text-[#1f2933]">Mật khẩu</Text>
                  <TextInput
                    className="rounded-xl border border-[#e0d8d0] bg-[#fcf9f3] px-4 py-3 text-base text-[#1f2933]"
                    placeholder="Tạo mật khẩu mạnh"
                    placeholderTextColor="#5b6773"
                    value={password}
                    onChangeText={setPassword}
                    secureTextEntry
                  />
                </View>

                <Pressable
                  className="mt-1 flex-row items-center justify-center gap-2 bg-[#145374] px-6 py-3 rounded-xl"
                  onPress={handleSignup}
                  disabled={loading}
                >
                  {loading ? (
                    <ActivityIndicator size="small" color="white" />
                  ) : (
                    <>
                      <Ionicons name="checkmark-circle" size={18} color="white" />
                      <Text className="text-base font-semibold text-white">Đăng ký</Text>
                    </>
                  )}
                </Pressable>
              </View>

              {/* Footer */}
              <Pressable
                className="mt-6 flex-row items-center justify-center gap-2"
                onPress={() => navigation.goBack()}
              >
                <Ionicons name="arrow-back" size={16} color="#5b6773" />
                <Text className="text-sm text-[#5b6773]">Quay lại đăng nhập</Text>
              </Pressable>
            </View>
          </ScrollView>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </ImageBackground>
  );
}

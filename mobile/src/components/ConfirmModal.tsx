import React from 'react';
import { View, Text, Modal, Pressable } from 'react-native';

interface ConfirmModalProps {
  visible: boolean;
  message: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmModal({ visible, message, onConfirm, onCancel }: ConfirmModalProps) {
  return (
    <Modal transparent animationType="fade" visible={visible} onRequestClose={onCancel}>
      <Pressable
        className="flex-1 items-center justify-center bg-black/40"
        onPress={onCancel}
      >
        <Pressable
          className="mx-6 w-[90%] max-w-[400px] bg-[#fcf9f3] p-6 border border-[#e0d8d0]"
          onPress={() => {}}
        >
          <Text className="mb-6 text-center text-lg font-semibold text-[#1f2933]">
            {message}
          </Text>
          <View className="flex-row justify-center gap-4">
            <Pressable
              className="flex-1 items-center border border-[#e0d8d0] bg-[#f4efe6] px-4 py-3"
              onPress={onCancel}
            >
              <Text className="font-semibold text-[#1f2933]">Hủy</Text>
            </Pressable>
            <Pressable
              className="flex-1 items-center bg-[#145374] px-4 py-3"
              onPress={onConfirm}
            >
              <Text className="font-semibold text-white">Xác nhận</Text>
            </Pressable>
          </View>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

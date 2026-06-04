import React from 'react';
import { View, Text, Pressable } from 'react-native';
import { Ionicons } from '@expo/vector-icons';

interface StatCardProps {
  icon: keyof typeof Ionicons.glyphMap;
  value: number;
  label: string;
  iconColor: string;
  onPress?: () => void;
}

export function StatCard({ icon, value, label, iconColor, onPress }: StatCardProps) {
  return (
    <Pressable 
      onPress={onPress}
      className={`flex-1 min-w-[140px] flex-row items-center gap-4 border border-[#e0d8d0]/60 bg-[#fcf9f3]/95 p-4 rounded-xl shadow-sm ${onPress ? 'active:opacity-70' : ''}`}
    >
      <View className="items-center justify-center h-12 w-12 rounded-full" style={{ backgroundColor: `${iconColor}15` }}>
        <Ionicons name={icon} size={24} color={iconColor} />
      </View>
      <View>
        <Text className="text-2xl font-bold text-[#1f2933]">{value}</Text>
        <Text className="text-xs text-[#5b6773]">{label}</Text>
      </View>
    </Pressable>
  );
}

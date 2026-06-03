import React from 'react';
import { ActivityIndicator, View } from 'react-native';
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { Ionicons } from '@expo/vector-icons';

import { useAuth } from '../contexts/AuthContext';
import { LoginScreen } from '../screens/LoginScreen';
import { SignupScreen } from '../screens/SignupScreen';
import { OverviewScreen } from '../screens/OverviewScreen';
import { AlarmsScreen } from '../screens/AlarmsScreen';
import { TimersScreen } from '../screens/TimersScreen';
import { ListsScreen } from '../screens/ListsScreen';
import { ProfileScreen } from '../screens/ProfileScreen';
import { MediaScreen } from '../screens/MediaScreen';

const AuthStack = createNativeStackNavigator();
const Tab = createBottomTabNavigator();
const ProfileStack = createNativeStackNavigator();

function ProfileStackScreen() {
  return (
    <ProfileStack.Navigator screenOptions={{ headerShown: false }}>
      <ProfileStack.Screen name="ProfileMain" component={ProfileScreen} />
      <ProfileStack.Screen
        name="MediaHistory"
        component={MediaScreen}
        options={{
          headerShown: true,
          title: 'Media History',
          headerStyle: { backgroundColor: '#f4efe6' },
          headerTintColor: '#1f2933',
          headerShadowVisible: false,
        }}
      />
    </ProfileStack.Navigator>
  );
}

function MainTabs() {
  return (
    <Tab.Navigator
      screenOptions={({ route }) => ({
        headerShown: false,
        tabBarActiveTintColor: '#145374',
        tabBarInactiveTintColor: '#5b6773',
        tabBarStyle: {
          backgroundColor: '#fcf9f3',
          borderTopColor: '#e0d8d0',
          borderTopWidth: 1,
          height: 85,
          paddingBottom: 28,
          paddingTop: 8,
        },
        tabBarLabelStyle: {
          fontSize: 11,
          fontWeight: '600',
        },
        tabBarIcon: ({ focused, color, size }) => {
          let iconName: keyof typeof Ionicons.glyphMap = 'home-outline';
          if (route.name === 'Tổng quan') {
            iconName = focused ? 'pie-chart' : 'pie-chart-outline';
          } else if (route.name === 'Báo thức') {
            iconName = focused ? 'time' : 'time-outline';
          } else if (route.name === 'Hẹn giờ') {
            iconName = focused ? 'hourglass' : 'hourglass-outline';
          } else if (route.name === 'Ghi chú') {
            iconName = focused ? 'document-text' : 'document-text-outline';
          } else if (route.name === 'Cá nhân') {
            iconName = focused ? 'person' : 'person-outline';
          }
          return <Ionicons name={iconName} size={22} color={color} />;
        },
      })}
    >
      <Tab.Screen name="Tổng quan" component={OverviewScreen} />
      <Tab.Screen name="Báo thức" component={AlarmsScreen} />
      <Tab.Screen name="Hẹn giờ" component={TimersScreen} />
      <Tab.Screen name="Ghi chú" component={ListsScreen} />
      <Tab.Screen name="Cá nhân" component={ProfileStackScreen} />
    </Tab.Navigator>
  );
}

export function AppNavigator() {
  const { isLoading, isLoggedIn } = useAuth();

  if (isLoading) {
    return (
      <View className="flex-1 items-center justify-center bg-[#f4efe6]">
        <ActivityIndicator size="large" color="#145374" />
      </View>
    );
  }

  return (
    <NavigationContainer>
      {isLoggedIn ? (
        <MainTabs />
      ) : (
        <AuthStack.Navigator screenOptions={{ headerShown: false }}>
          <AuthStack.Screen name="Login" component={LoginScreen} />
          <AuthStack.Screen name="Signup" component={SignupScreen} />
        </AuthStack.Navigator>
      )}
    </NavigationContainer>
  );
}

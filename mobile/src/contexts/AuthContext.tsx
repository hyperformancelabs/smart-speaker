import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';

interface AuthState {
  isLoading: boolean;
  isLoggedIn: boolean;
  userId: string;
  nfcTagId: string;
  userName: string;
  displayName: string;
}

interface AuthContextType extends AuthState {
  login: (data: {
    user_id: string;
    nfc_tag_id: string;
    user_name: string;
    name: string;
  }) => Promise<void>;
  logout: () => Promise<void>;
  updateProfile: (name: string, userName: string) => Promise<void>;
}

const AuthContext = createContext<AuthContextType>({} as AuthContextType);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<AuthState>({
    isLoading: true,
    isLoggedIn: false,
    userId: '',
    nfcTagId: '',
    userName: '',
    displayName: '',
  });

  useEffect(() => {
    (async () => {
      try {
        const nfc = await AsyncStorage.getItem('nfcTagId');
        if (nfc) {
          const [userId, userName, displayName] = await Promise.all([
            AsyncStorage.getItem('userId'),
            AsyncStorage.getItem('userName'),
            AsyncStorage.getItem('displayName'),
          ]);
          setState({
            isLoading: false,
            isLoggedIn: true,
            userId: userId || '',
            nfcTagId: nfc,
            userName: userName || '',
            displayName: displayName || '',
          });
        } else {
          setState((s) => ({ ...s, isLoading: false }));
        }
      } catch {
        setState((s) => ({ ...s, isLoading: false }));
      }
    })();
  }, []);

  const login = useCallback(
    async (data: { user_id: string; nfc_tag_id: string; user_name: string; name: string }) => {
      await AsyncStorage.multiSet([
        ['userId', data.user_id],
        ['nfcTagId', data.nfc_tag_id],
        ['userName', data.user_name || ''],
        ['displayName', data.name || ''],
      ]);
      setState({
        isLoading: false,
        isLoggedIn: true,
        userId: data.user_id,
        nfcTagId: data.nfc_tag_id,
        userName: data.user_name || '',
        displayName: data.name || '',
      });
    },
    [],
  );

  const logout = useCallback(async () => {
    await AsyncStorage.multiRemove(['userId', 'nfcTagId', 'userName', 'displayName']);
    setState({
      isLoading: false,
      isLoggedIn: false,
      userId: '',
      nfcTagId: '',
      userName: '',
      displayName: '',
    });
  }, []);

  const updateProfile = useCallback(async (name: string, userName: string) => {
    await AsyncStorage.multiSet([
      ['userName', userName],
      ['displayName', name],
    ]);
    setState((s) => ({ ...s, userName, displayName: name }));
  }, []);

  return (
    <AuthContext.Provider value={{ ...state, login, logout, updateProfile }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);

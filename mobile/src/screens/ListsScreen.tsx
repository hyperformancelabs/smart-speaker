import React, { useCallback, useState } from 'react';
import {
  View,
  Text,
  ScrollView,
  TextInput,
  Pressable,
  ActivityIndicator,
  Alert,
  Modal,
  RefreshControl,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useFocusEffect } from '@react-navigation/native';
import { Ionicons } from '@expo/vector-icons';
import { NoteList, ListAPI } from '../services/api';
import { ConfirmModal } from '../components/ConfirmModal';

export function ListsScreen() {
  const [lists, setLists] = useState<NoteList[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [newListName, setNewListName] = useState('');

  // Note inputs per list
  const [noteInputs, setNoteInputs] = useState<Record<string, string>>({});

  // Edit modal
  const [editModal, setEditModal] = useState(false);
  const [editType, setEditType] = useState<'list' | 'note'>('list');
  const [editListId, setEditListId] = useState('');
  const [editNoteId, setEditNoteId] = useState('');
  const [editContent, setEditContent] = useState('');

  // Delete confirm
  const [deleteTarget, setDeleteTarget] = useState<{
    type: 'list' | 'note';
    listId: string;
    noteId?: string;
  } | null>(null);

  const fetchLists = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    try {
      const data = await ListAPI.getAll();
      setLists(data);
    } catch {
      // keep
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      fetchLists();
    }, [fetchLists]),
  );

  const handleCreateList = async () => {
    if (!newListName.trim()) return;
    try {
      await ListAPI.createList(newListName.trim());
      setNewListName('');
      fetchLists();
    } catch (e: any) {
      Alert.alert('Lỗi', e.message || 'Không thể tạo danh sách.');
    }
  };

  const handleAddNote = async (listId: string) => {
    const content = (noteInputs[listId] || '').trim();
    if (!content) return;
    try {
      await ListAPI.addNote(listId, content);
      setNoteInputs((prev) => ({ ...prev, [listId]: '' }));
      fetchLists();
    } catch {
      Alert.alert('Lỗi', 'Không thể thêm ghi chú.');
    }
  };

  const handleToggleNote = async (listId: string, itemId: string, completed: boolean) => {
    try {
      await ListAPI.updateNoteCompleted(listId, itemId, completed);
      fetchLists();
    } catch {
      Alert.alert('Lỗi', 'Không thể cập nhật trạng thái.');
    }
  };

  const openEditModal = (
    type: 'list' | 'note',
    listId: string,
    noteId: string,
    content: string,
  ) => {
    setEditType(type);
    setEditListId(listId);
    setEditNoteId(noteId);
    setEditContent(content);
    setEditModal(true);
  };

  const handleEditSave = async () => {
    if (!editContent.trim()) return;
    try {
      if (editType === 'list') {
        await ListAPI.renameList(editListId, editContent.trim());
      } else {
        await ListAPI.updateNote(editListId, editNoteId, editContent.trim());
      }
      setEditModal(false);
      fetchLists();
    } catch {
      Alert.alert('Lỗi', 'Không thể cập nhật.');
    }
  };

  const handleDeleteConfirm = async () => {
    if (!deleteTarget) return;
    try {
      if (deleteTarget.type === 'list') {
        await ListAPI.deleteList(deleteTarget.listId);
      } else if (deleteTarget.noteId) {
        await ListAPI.deleteNote(deleteTarget.listId, deleteTarget.noteId);
      }
      setDeleteTarget(null);
      fetchLists();
    } catch {
      Alert.alert('Lỗi', 'Không thể xóa.');
      setDeleteTarget(null);
    }
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
      <View className="flex-1">
        {/* Header */}
        <View className="gap-3 px-4 pt-4 pb-2">
          <Text className="text-xl font-bold text-[#1f2933]">
            <Ionicons name="document-text-outline" size={20} color="#1f2933" /> Ghi chú & Công
            việc
          </Text>
          <View className="flex-row gap-2">
            <TextInput
              className="flex-1 border border-[#e0d8d0] bg-[#fcf9f3] px-3 py-2 text-[#1f2933]"
              placeholder="Tên danh sách mới..."
              placeholderTextColor="#5b6773"
              value={newListName}
              onChangeText={setNewListName}
            />
            <Pressable
              className="flex-row items-center gap-1 bg-[#145374] px-4 py-2"
              onPress={handleCreateList}
            >
              <Ionicons name="add" size={16} color="white" />
              <Text className="font-semibold text-white">Tạo</Text>
            </Pressable>
          </View>
        </View>

        <ScrollView
          contentContainerClassName="px-4 pb-8 gap-4"
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={() => fetchLists(true)} />
          }
        >
          {lists.length === 0 ? (
            <View className="items-center py-12">
              <Ionicons name="folder-open-outline" size={48} color="#5b6773" />
              <Text className="mt-3 text-center text-[#5b6773]">
                Chưa có danh sách ghi chú nào. Hãy tạo một cái mới.
              </Text>
            </View>
          ) : (
            lists.map((list) => (
              <View key={list.list_id} className="border border-[#e0d8d0] bg-[#fcf9f3] p-4 gap-3">
                {/* List header */}
                <View className="flex-row items-center justify-between border-b border-b-[#e0d8d0] pb-2">
                  <Text className="text-lg font-semibold text-[#1f2933]">{list.list_name}</Text>
                  <View className="flex-row gap-1">
                    <Pressable
                      className="p-1"
                      onPress={() =>
                        openEditModal('list', list.list_id, '', list.list_name)
                      }
                    >
                      <Ionicons name="pencil" size={16} color="#5b6773" />
                    </Pressable>
                    <Pressable
                      className="p-1"
                      onPress={() =>
                        setDeleteTarget({ type: 'list', listId: list.list_id })
                      }
                    >
                      <Ionicons name="trash-outline" size={16} color="#a43f24" />
                    </Pressable>
                  </View>
                </View>

                {/* Notes */}
                {(!list.items || list.items.length === 0) ? (
                  <Text className="py-2 text-center text-sm text-[#5b6773]">
                    Danh sách trống
                  </Text>
                ) : (
                  list.items.map((note) => (
                    <View
                      key={note.item_id}
                      className="flex-row items-start justify-between gap-2 bg-[#fcf9f3] p-3"
                    >
                      <Pressable
                        className="flex-1 flex-row items-start gap-3"
                        onPress={() =>
                          handleToggleNote(list.list_id, note.item_id, !note.completed)
                        }
                      >
                        <Ionicons
                          name={note.completed ? 'checkbox' : 'square-outline'}
                          size={20}
                          color={note.completed ? '#145374' : '#5b6773'}
                          style={{ marginTop: 2 }}
                        />
                        <Text
                          className={`flex-1 text-base leading-snug ${
                            note.completed
                              ? 'text-[#5b6773] line-through'
                              : 'text-[#1f2933]'
                          }`}
                        >
                          {note.content}
                        </Text>
                      </Pressable>
                      <View className="flex-row gap-0">
                        <Pressable
                          className="p-1"
                          onPress={() =>
                            openEditModal(
                              'note',
                              list.list_id,
                              note.item_id,
                              note.content,
                            )
                          }
                        >
                          <Ionicons name="pencil" size={14} color="#5b6773" />
                        </Pressable>
                        <Pressable
                          className="p-1"
                          onPress={() =>
                            setDeleteTarget({
                              type: 'note',
                              listId: list.list_id,
                              noteId: note.item_id,
                            })
                          }
                        >
                          <Ionicons name="close" size={16} color="#a43f24" />
                        </Pressable>
                      </View>
                    </View>
                  ))
                )}

                {/* Add note input */}
                <View className="flex-row gap-2">
                  <TextInput
                    className="flex-1 border border-[#e0d8d0] bg-[#fcf9f3] px-3 py-2 text-sm text-[#1f2933]"
                    placeholder="Thêm ghi chú..."
                    placeholderTextColor="#5b6773"
                    value={noteInputs[list.list_id] || ''}
                    onChangeText={(text) =>
                      setNoteInputs((prev) => ({ ...prev, [list.list_id]: text }))
                    }
                    onSubmitEditing={() => handleAddNote(list.list_id)}
                  />
                  <Pressable
                    className="items-center justify-center bg-[#145374] px-3 py-2"
                    onPress={() => handleAddNote(list.list_id)}
                  >
                    <Ionicons name="send" size={16} color="white" />
                  </Pressable>
                </View>
              </View>
            ))
          )}
        </ScrollView>

        {/* Edit Modal */}
        <Modal
          transparent
          animationType="fade"
          visible={editModal}
          onRequestClose={() => setEditModal(false)}
        >
          <Pressable
            className="flex-1 items-center justify-center bg-black/40"
            onPress={() => setEditModal(false)}
          >
            <Pressable
              className="mx-6 w-[90%] max-w-[400px] border border-[#e0d8d0] bg-[#fcf9f3] p-6"
              onPress={() => {}}
            >
              <Text className="mb-4 text-xl font-bold text-[#1f2933]">
                {editType === 'list' ? 'Sửa tên danh sách' : 'Sửa ghi chú'}
              </Text>
              <View className="gap-1 mb-4">
                <Text className="text-sm font-medium text-[#1f2933]">
                  {editType === 'list' ? 'Tên danh sách mới' : 'Nội dung mới'}
                </Text>
                <TextInput
                  className="border border-[#e0d8d0] bg-[#fcf9f3] px-4 py-3 text-base text-[#1f2933]"
                  value={editContent}
                  onChangeText={setEditContent}
                  autoFocus
                />
              </View>
              <View className="flex-row gap-3">
                <Pressable
                  className="flex-1 items-center border border-[#e0d8d0] bg-[#f4efe6] py-3"
                  onPress={() => setEditModal(false)}
                >
                  <Text className="font-semibold text-[#1f2933]">Hủy</Text>
                </Pressable>
                <Pressable
                  className="flex-1 items-center bg-[#145374] py-3"
                  onPress={handleEditSave}
                >
                  <Text className="font-semibold text-white">Lưu</Text>
                </Pressable>
              </View>
            </Pressable>
          </Pressable>
        </Modal>

        {/* Delete Confirm */}
        <ConfirmModal
          visible={deleteTarget !== null}
          message={
            deleteTarget?.type === 'list'
              ? 'Bạn có chắc chắn muốn xóa danh sách này cùng các ghi chú bên trong?'
              : 'Bạn có chắc chắn muốn xóa ghi chú này?'
          }
          onConfirm={handleDeleteConfirm}
          onCancel={() => setDeleteTarget(null)}
        />
      </View>
    </SafeAreaView>
  );
}

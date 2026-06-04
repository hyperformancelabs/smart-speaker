# Single-Turn Matrix Log

Backend: `http://127.0.0.1:8387`
Mode: `DISABLE_TTS=true` for API verification

## Verified Cases

| # | Input | Expected | Observed |
|---|---|---|---|
| 1 | `Phát bài Lạc Trôi của Sơn Tùng M-TP` | media, completed, play music | `route=media`, `status=completed`, tool=`youtube_search`, TTS: `Mình phát bài Lạc Trôi...` |
| 2 | `Phát bài lạch rôi của Sơn Tùng Entity` | media, completed, noisy STT still resolves | `route=media`, `status=completed`, tool=`youtube_search`, TTS: `Mình tìm thấy bài Lạc Trôi...` |
| 3 | `Phát bài chóng lên 3` | media, needs_clarification | `route=media`, `status=needs_clarification`, tool=`youtube_search`, TTS asks for clearer song/artist |
| 4 | `play bài lo fi study mix` | media, completed | `route=media`, `status=completed`, tool=`youtube_search`, TTS: `Mình sẽ mở nhạc lofi study mix...` |
| 5 | `Tin mới nhất về Apple là gì?` | information_query, completed | `route=information_query`, `status=completed`, tool=`web_search`, TTS: Apple news summary |
| 6 | `15 nhân 12 bằng bao nhiêu?` | information_query, completed | `route=information_query`, `status=completed`, tool=`calculator`, TTS: `mười lăm nhân mười hai bằng một trăm tám mươi...` |
| 7 | `Tính bmi cho 70kg 1m75` | information_query, completed | `route=information_query`, `status=completed`, tool=`calculator`, TTS: BMI around `22.9` |
| 8 | `Hôm nay thời tiết Đà Nẵng thế nào?` | information_query, completed / safe fallback | `route=information_query`, `status=completed`, tool=`web_search`, TTS: safe fallback when detailed weather unavailable |
| 9 | `Thêm trứng vào danh sách mua sắm` | productivity, completed | `route=productivity`, `status=completed`, tool=`add_list_item`, TTS: item added |
| 10 | `Kiểm tra các danh sách hiện có` | productivity, completed | `route=productivity`, `status=completed`, tool=`get_lists`, TTS: current shopping list contents |
| 11 | `thêm vào danh sách` | productivity, needs_clarification | `route=productivity`, `status=needs_clarification`, no tool call, TTS asks what item / which list |
| 12 | `xóa danh sách mua sắm` | productivity, completed | `route=productivity`, `status=completed`, tool=`delete_list`, TTS confirms deletion |
| 13 | `Bạn nhớ gì về tôi?` | personalization, completed | `route=personalization`, `status=completed`, tools=`get_user_profile`, `get_memory`, TTS says no memories stored |
| 14 | `Hãy nhớ rằng tôi thích nghe nhạc acoustic khi học bài` | personalization, completed | `route=personalization`, `status=completed`, tool=`update_user_profile`, TTS confirms memory saved |
| 15 | `quên hết memory của tôi` | personalization, completed | `route=personalization`, `status=completed`, tool=`reset_memory`, TTS confirms memory reset to default |
| 16 | `reset memory` | personalization, completed | `route=personalization`, `status=completed`, tool=`reset_memory`, TTS confirms memory reset to default |
| 17 | `đưa preferences về mặc định` | personalization, completed | `route=personalization`, `status=completed`, tool=`reset_preferences`, TTS confirms preferences reset |
| 18 | `reset context` | conversation, completed | `route=conversation`, `status=completed`, no tool call, TTS resets chat context only |
| 19 | `Chào bạn nhé` | conversation, completed | `route=conversation`, `status=completed`, no tool call, friendly greeting |
| 20 | `Hello, good morning` | conversation, completed | `route=conversation`, `status=completed`, no tool call, English greeting handled |
| 21 | `Tell me a joke` | conversation, completed | `route=conversation`, `status=completed`, no tool call, joke response |
| 22 | `What is blockchain?` | information_query, completed | `route=information_query`, `status=completed`, tool=`web_search`, English definition summary |
| 23 | `Search something for me` | information_query, needs_clarification | expected ambiguity handling |
| 24 | `thêm sữa vào danh sách mua sắm rồi phát lạc trôi` | negative, single-turn should not execute two intents | should be treated as unclear / single-intent only |

## Notes

- Positive coverage:
  - media
  - information lookup
  - calculations
  - productivity list CRUD
  - personalization read/save/reset
  - conversation
  - English and Vietnamese
- Negative coverage:
  - ambiguous media
  - ambiguous list add
  - ambiguous info request
  - multi-intent single utterance
- Verified live backend behavior:
  - `reset_memory` is routed to `personalization`
  - `reset_preferences` is routed to `personalization`
  - `reset context` stays in `conversation`


TOOLS_DEFINITIONS = [
    {
        "name": "youtube_search",
        "description": "Tìm video YouTube qua yt-dlp và trả về danh sách kết quả đầu tiên để đối chiếu với yêu cầu STT của user.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Từ khóa tìm video hoặc nhạc"},
                "max_results": {"type": "integer", "description": "Số kết quả tối đa cần lấy"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "youtube_stream",
        "description": "Lấy stream YouTube qua yt-dlp và trả proxy URL phù hợp cho ESP32 phát audio hoặc video.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query để lấy video đầu tiên phù hợp"},
                "video_id": {"type": "string", "description": "YouTube video ID cụ thể"},
                "url": {"type": "string", "description": "URL YouTube đầy đủ"},
                "mode": {"type": "string", "enum": ["audio", "video"], "description": "Loại stream cần lấy"},
            },
        },
    },
    {
        "name": "play_audio",
        "description": "Shortcut phát audio từ YouTube bằng cách lấy stream audio trực tiếp.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Nội dung audio cần phát"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "web_search",
        "description": "Tìm kiếm web, lấy danh sách kết quả và nội dung rút gọn để trả lời fact/news/definition.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Nội dung cần tìm"},
                "max_results": {"type": "integer", "description": "Số kết quả tối đa"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "fetch_content",
        "description": "Đọc nội dung trực tiếp từ danh sách URL để LLM tổng hợp câu trả lời.",
        "input_schema": {
            "type": "object",
            "properties": {
                "urls": {"type": "array", "description": "Danh sách URL cần đọc"},
                "max_items": {"type": "integer", "description": "Số URL tối đa cần fetch"},
                "max_content_chars": {"type": "integer", "description": "Giới hạn ký tự mỗi trang"},
            },
            "required": ["urls"],
        },
    },
    {
        "name": "calculator",
        "description": "Tính toán biểu thức toán học an toàn và trả kết quả số.",
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "Biểu thức toán học cần tính"},
            },
            "required": ["expression"],
        },
    },
    {
        "name": "create_alarm",
        "description": "Tạo báo thức mới theo giờ cố định, thời điểm cụ thể, hoặc sau một khoảng thời gian.",
        "input_schema": {
            "type": "object",
            "properties": {
                "label": {"type": "string", "description": "Mô tả báo thức"},
                "time": {"type": "string", "description": "Giờ báo thức định dạng HH:MM khi schedule_type=time"},
                "repeat": {"type": "string", "enum": ["once", "daily", "weekly"], "description": "Tần suất lặp"},
                "schedule_type": {
                    "type": "string",
                    "enum": ["time", "datetime", "relative"],
                    "description": "Kiểu báo thức",
                },
                "scheduled_for": {
                    "type": "string",
                    "description": "ISO datetime khi schedule_type=datetime, ví dụ 2026-04-12T07:30:00+07:00",
                },
                "offset_seconds": {
                    "type": "integer",
                    "description": "Số giây tính từ hiện tại khi schedule_type=relative",
                },
            },
            "required": ["label"],
        },
    },
    {
        "name": "update_alarm",
        "description": "Cập nhật báo thức hiện có.",
        "input_schema": {
            "type": "object",
            "properties": {
                "alarm_id": {"type": "string", "description": "ID báo thức cần cập nhật"},
                "label": {"type": "string", "description": "Nhãn mới"},
                "time": {"type": "string", "description": "Giờ mới theo HH:MM"},
                "repeat": {"type": "string", "enum": ["once", "daily", "weekly"]},
                "schedule_type": {"type": "string", "enum": ["time", "datetime", "relative"]},
                "scheduled_for": {"type": "string", "description": "ISO datetime mới"},
                "offset_seconds": {"type": "integer", "description": "Số giây mới từ hiện tại"},
            },
            "required": ["alarm_id"],
        },
    },
    {
        "name": "delete_alarm",
        "description": "Xóa báo thức.",
        "input_schema": {
            "type": "object",
            "properties": {
                "alarm_id": {"type": "string", "description": "ID báo thức cần xóa"},
            },
            "required": ["alarm_id"],
        },
    },
    {
        "name": "list_alarms",
        "description": "Liệt kê tất cả báo thức của user hiện tại.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "start_timer",
        "description": "Bắt đầu bộ đếm ngược với duration dạng ngày, giờ, phút, giây.",
        "input_schema": {
            "type": "object",
            "properties": {
                "duration": {"type": "string", "description": "Ví dụ: 1d2h, 10m, 90s"},
                "label": {"type": "string", "description": "Tên timer"},
            },
            "required": ["duration"],
        },
    },
    {
        "name": "list_timers",
        "description": "Liệt kê tất cả timer đang hoạt động.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "update_timer",
        "description": "Cập nhật duration hoặc label của timer đang hoạt động.",
        "input_schema": {
            "type": "object",
            "properties": {
                "timer_id": {"type": "string", "description": "ID timer cần cập nhật"},
                "duration": {"type": "string", "description": "Duration mới"},
                "label": {"type": "string", "description": "Label mới"},
            },
            "required": ["timer_id"],
        },
    },
    {
        "name": "cancel_timer",
        "description": "Hủy bộ đếm ngược.",
        "input_schema": {
            "type": "object",
            "properties": {
                "timer_id": {"type": "string", "description": "ID timer cần hủy"},
            },
            "required": ["timer_id"],
        },
    },
    {
        "name": "create_list",
        "description": "Tạo danh sách mới như todo, shopping list, note list.",
        "input_schema": {
            "type": "object",
            "properties": {
                "list_name": {"type": "string", "description": "Tên danh sách"},
            },
            "required": ["list_name"],
        },
    },
    {
        "name": "rename_list",
        "description": "Đổi tên danh sách hiện có.",
        "input_schema": {
            "type": "object",
            "properties": {
                "list_name": {"type": "string", "description": "Tên danh sách hiện tại"},
                "new_list_name": {"type": "string", "description": "Tên danh sách mới"},
            },
            "required": ["list_name", "new_list_name"],
        },
    },
    {
        "name": "delete_list",
        "description": "Xóa toàn bộ danh sách.",
        "input_schema": {
            "type": "object",
            "properties": {
                "list_name": {"type": "string", "description": "Tên danh sách cần xóa"},
            },
            "required": ["list_name"],
        },
    },
    {
        "name": "add_list_item",
        "description": "Thêm mục vào danh sách.",
        "input_schema": {
            "type": "object",
            "properties": {
                "list_name": {"type": "string", "description": "Tên danh sách"},
                "item": {"type": "string", "description": "Nội dung mục cần thêm"},
            },
            "required": ["list_name", "item"],
        },
    },
    {
        "name": "update_list_item",
        "description": "Cập nhật nội dung hoặc trạng thái completed của một item trong danh sách.",
        "input_schema": {
            "type": "object",
            "properties": {
                "list_name": {"type": "string", "description": "Tên danh sách"},
                "item": {"type": "string", "description": "Nội dung item hiện tại"},
                "new_item": {"type": "string", "description": "Nội dung mới"},
                "completed": {"type": "boolean", "description": "Đánh dấu hoàn thành hay chưa"},
            },
            "required": ["list_name", "item"],
        },
    },
    {
        "name": "remove_list_item",
        "description": "Xóa mục khỏi danh sách.",
        "input_schema": {
            "type": "object",
            "properties": {
                "list_name": {"type": "string", "description": "Tên danh sách"},
                "item": {"type": "string", "description": "Nội dung mục cần xóa"},
            },
            "required": ["list_name", "item"],
        },
    },
    {
        "name": "get_lists",
        "description": "Lấy toàn bộ danh sách kèm item của user.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_items",
        "description": "Liệt kê item của một danh sách cụ thể.",
        "input_schema": {
            "type": "object",
            "properties": {
                "list_name": {"type": "string", "description": "Tên danh sách"},
            },
            "required": ["list_name"],
        },
    },
    {
        "name": "get_user_profile",
        "description": "Lấy thông tin cá nhân hiện tại của user.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "update_user_profile",
        "description": "Cập nhật thông tin user như name, user_name, traits, preferences, user_password. Với field=preferences, value nên là object JSON partial để merge vào preferences hiện có; được phép thêm key mới.",
        "input_schema": {
            "type": "object",
            "properties": {
                "field": {"type": "string", "description": "Tên field cần cập nhật"},
                "value": {
                    "type": ["string", "object", "array", "number", "boolean"],
                    "description": "Giá trị mới. Với field=preferences, ưu tiên truyền object JSON partial.",
                },
            },
            "required": ["field", "value"],
        },
    },
    {
        "name": "save_memory",
        "description": "Lưu một memory mới cho user hiện tại.",
        "input_schema": {
            "type": "object",
            "properties": {
                "memory": {"type": "string", "description": "Thông tin cần lưu"},
            },
            "required": ["memory"],
        },
    },
    {
        "name": "delete_memory",
        "description": "Xóa một memory đã lưu.",
        "input_schema": {
            "type": "object",
            "properties": {
                "memory": {"type": "string", "description": "Thông tin cần xóa khỏi memory"},
            },
            "required": ["memory"],
        },
    },
    {
        "name": "get_memory",
        "description": "Lấy toàn bộ memory cá nhân của user.",
        "input_schema": {"type": "object", "properties": {}},
    },
]


def get_tool_schema(tool_name: str):
    for tool in TOOLS_DEFINITIONS:
        if tool["name"] == tool_name:
            return tool
    return None


def get_all_tool_names():
    return [tool["name"] for tool in TOOLS_DEFINITIONS]

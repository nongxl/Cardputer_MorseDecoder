# main.py
# M5Stack Cardputer 莫斯电码翻译器
# 最终生产版 - 为兼容旧固件，菜单使用默认字体

import M5
from M5 import Widgets, Speaker
from hardware.matrix_keyboard import MatrixKeyboard
import time
import sys

# --- [1] 状态机和全局变量 ---
# 主界面显示内容
output_string = "Ready."
last_input_display_string = ""
input_string = ""

# --- 新增：主界面输出滚动状态 ---
output_lines = []
output_scroll_top_line = 0

# 菜单定义
ACTIONS = ["Play Demo", "Speaker", "Presets", "Switch Mode"]

# --- UI元素 ---
# 主界面 (Widgets)
# [优化] 使用两个独立的Label实现可靠的换行输出
output_label_1 = None
output_label_2 = None
last_input_label = None
current_mode_label = None
input_label = None
tab_hint_label = None
# 菜单 (Lcd)
options_menu = None
preset_list = None

# --- 系统状态 ---
kb = None
last_key_state = False
MODES = ["Text -> Morse", "Morse -> Text"]
current_mode_index = 0
last_morse_output = ""  # This will now contain '/' for word gaps
speaker_on = False

# --- 模态状态 ---
is_menu_active = False
is_selecting_preset = False

# --- 数据常量 ---
PRESETS = {
    "SOS": "... --- ...",
    "CQ": "-.-. --.-",
    "73": "--... ...--",
    "HELLO": ".... . .-.. .-.. ---",
    "QTH?": "--.- - .... ..--..",
    "MY NAME IS": "-- -.-- / -. .- -- . / .. ...",
    "TEST": "- . ... -",
    "DE": "-.. .",
    "K": "-.-"
}
PRESET_KEYS = list(PRESETS.keys())

CHAR_TO_MORSE = {
    'A': '.-', 'B': '-...', 'C': '-.-.', 'D': '-..', 'E': '.', 'F': '..-.', 'G': '--.', 'H': '....',
    'I': '..', 'J': '.---', 'K': '-.-', 'L': '.-..', 'M': '--', 'N': '-.', 'O': '---', 'P': '.--.',
    'Q': '--.-', 'R': '.-.', 'S': '...', 'T': '-', 'U': '..-', 'V': '...-', 'W': '.--', 'X': '-..-',
    'Y': '-.--', 'Z': '--..', '1': '.----', '2': '..---', '3': '...--', '4': '....-', '5': '.....',
    '6': '-....', '7': '--...', '8': '---..', '9': '----.', '0': '-----',
    '.': '.-.-.-', ',': '--..--', '?': '..--..', "'": '.----.', '!': '-.-.--', '/': '-..-.',
    '(': '-.--.', ')': '-.--.-', '&': '.-...', ':': '---...', ';': '-.-.-.', '=': '-...-',
    '+': '.-.-.', '-': '-....-', '_': '..--.-', '"': '.-..-.', '$': '...-..-', '@': '.--.-.'
}
MORSE_TO_CHAR = {v: k for k, v in CHAR_TO_MORSE.items()}


# --- [2] UI类定义 (底层Lcd绘制) ---

class LcdOptionsMenu:
    """一个“哑”的、支持滚动的模态选项菜单。"""

    def __init__(self, x, y, w, h, items, title=""):
        self.x, self.y, self.w, self.h = x, y, w, h
        self.items = items
        self.title = title
        self.selected_index = 0
        self.visible = False
        self.dirty = True

        # --- 滚动状态 ---
        self.top_item_index = 0

        # [最终方案] 恢复2倍字体，但使用更紧凑的布局
        self.item_row_height = 22  # 优化行高
        self.title_area_height = 28  # 优化标题区域高度
        self.max_visible_items = (self.h - self.title_area_height) // self.item_row_height

        # 颜色和字体定义
        self.text_color = 0x222222
        self.bg_color = 0xe9e8e8
        self.selected_text_color = 0xffffff
        self.selected_bg_color = 0x007acc
        self.title_bg_color = 0xcccccc
        self.scroll_indicator_color = 0x888888

    def show(self):
        self.visible = True
        self.selected_index = 0
        self.top_item_index = 0
        self.dirty = True

    def hide(self):
        self.visible = False

    def handle_key(self, key_str):
        if not self.visible:
            return None

        if key_str == ';':  # Up
            self.selected_index = (self.selected_index - 1 + len(self.items)) % len(self.items)
            if self.selected_index < self.top_item_index:
                self.top_item_index = self.selected_index
            elif self.selected_index == len(self.items) - 1:
                self.top_item_index = max(0, len(self.items) - self.max_visible_items)
            self.dirty = True
        elif key_str == '.':  # Down
            self.selected_index = (self.selected_index + 1) % len(self.items)
            if self.selected_index >= self.top_item_index + self.max_visible_items:
                self.top_item_index = self.selected_index - self.max_visible_items + 1
            elif self.selected_index == 0:
                self.top_item_index = 0
            self.dirty = True
        elif key_str in ('enter', '\r','\n'):
            return self.items[self.selected_index]
        elif key_str in ('`', '\x1b'):
            return 'close'
        return None

    def draw(self):
        if not self.visible or not self.dirty:
            return

        # [最终方案] 使用2倍大小的默认字体
        M5.Lcd.setTextSize(2)
        M5.Lcd.fillRect(self.x, self.y, self.w, self.h, self.bg_color)
        M5.Lcd.fillRect(self.x, self.y, self.w, 24, self.title_bg_color)
        M5.Lcd.setTextColor(self.text_color, self.title_bg_color)
        M5.Lcd.setCursor(self.x + 8, self.y + 5)
        M5.Lcd.print(self.title)

        # 绘制视口内的项目
        for i in range(self.max_visible_items):
            item_global_index = self.top_item_index + i
            if item_global_index >= len(self.items):
                break

            item_y = self.y + self.title_area_height + (i * self.item_row_height)
            item_text_base = self.items[item_global_index]
            text = f"Speaker: {'ON' if speaker_on else 'OFF'}" if item_text_base == "Speaker" else item_text_base

            if item_global_index == self.selected_index:
                M5.Lcd.fillRect(self.x + 2, item_y - 2, self.w - 4, 20, self.selected_bg_color)
                M5.Lcd.setTextColor(self.selected_text_color, self.selected_bg_color)
            else:
                M5.Lcd.setTextColor(self.text_color, self.bg_color)

            M5.Lcd.setCursor(self.x + 10, item_y)
            M5.Lcd.print(text)

        # 绘制滚动指示器
        if len(self.items) > self.max_visible_items:
            if self.top_item_index > 0:
                M5.Lcd.fillTriangle(self.x + self.w - 18, self.y + 8, self.x + self.w - 23, self.y + 16,
                                    self.x + self.w - 13, self.y + 16, self.scroll_indicator_color)
            if self.top_item_index + self.max_visible_items < len(self.items):
                M5.Lcd.fillTriangle(self.x + self.w - 18, self.y + self.h - 8, self.x + self.w - 23,
                                    self.y + self.h - 16, self.x + self.w - 13, self.y + self.h - 16,
                                    self.scroll_indicator_color)

        self.dirty = False


# --- [3] 核心函数 ---

def wrap_text_by_char(text, max_chars):
    """基于字符数的文本换行"""
    lines = []
    words = text.split(' ')
    current_line = ""
    for word in words:
        if len(current_line) + len(word) + 1 > max_chars:
            lines.append(current_line)
            current_line = word
        else:
            if current_line:
                current_line += " " + word
            else:
                current_line = word
    if current_line:
        lines.append(current_line)
    return lines if lines else [""]


def draw_scroll_arrows(show_up, show_down):
    """手动绘制和擦除滚动箭头"""
    arrow_area_x = 225
    arrow_area_y = 22
    arrow_area_w = 15
    arrow_area_h = 45
    arrow_color = 0xcccccc

    M5.Lcd.fillRect(arrow_area_x, arrow_area_y, arrow_area_w, arrow_area_h, 0xffffff)

    if show_up:
        M5.Lcd.fillTriangle(230, 25, 225, 32, 235, 32, arrow_color)

    if show_down:
        M5.Lcd.fillTriangle(230, 60, 225, 53, 235, 53, arrow_color)


def update_output_display():
    """根据滚动状态更新输出区域的显示"""
    global output_lines, output_scroll_top_line, output_label_1, output_label_2

    # [优化] 从 output_lines 数组中获取要显示的两行文本
    line1_text = output_lines[output_scroll_top_line] if output_scroll_top_line < len(output_lines) else ""
    line2_index = output_scroll_top_line + 1
    line2_text = output_lines[line2_index] if line2_index < len(output_lines) else ""

    # [优化] 将文本分别设置到两个独立的Label上
    output_label_1.setText(line1_text)
    output_label_2.setText(line2_text)

    # 更新滚动箭头的可见性
    can_scroll_up = output_scroll_top_line > 0
    # [优化] 滚动逻辑现在基于总行数
    can_scroll_down = output_scroll_top_line + 2 < len(output_lines)
    draw_scroll_arrows(can_scroll_up, can_scroll_down)


def force_all_widgets_redraw():
    """通过“清空-赋值”技巧强制所有Widgets重绘"""
    # [优化] 清空并更新两个输出Label
    output_label_1.setText("")
    output_label_2.setText("")
    update_output_display()

    last_input_label.setText("")
    last_input_label.setText(last_input_display_string)

    current_mode_label.setText("")
    current_mode_label.setText(MODES[current_mode_index])

    input_label.setText("")
    input_label.setText(">" + input_string)

    # [修正] 增加对tab_hint_label的重绘，解决其消失的问题
    tab_hint_label.setText("")
    tab_hint_label.setText("menu: tab")


def restore_ui_after_menu_close(menu_to_clear):
    """精确擦除菜单区域并恢复UI"""
    M5.Lcd.fillRect(menu_to_clear.x, menu_to_clear.y, menu_to_clear.w, menu_to_clear.h, 0xffffff)
    force_all_widgets_redraw()


def setup():
    global kb, options_menu, preset_list
    global output_label_1, output_label_2, last_input_label, current_mode_label, input_label, tab_hint_label
    global output_lines
    M5.begin()
    Widgets.fillScreen(0xffffff)

    # --- 主UI控件 ---
    last_input_label = Widgets.Label("", 8, 4, 1.0, 0x888888, 0xffffff, Widgets.FONTS.DejaVu12)
    tab_hint_label = Widgets.Label("menu: tab", 160, 4, 1.0, 0x888888, 0xffffff, Widgets.FONTS.DejaVu12)

    # [优化] 创建两个独立的Label用于输出，确保换行可靠
    output_label_1 = Widgets.Label("", 8, 22, 1.0, 0x000000, 0xffffff, Widgets.FONTS.DejaVu18)
    output_label_2 = Widgets.Label("", 8, 42, 1.0, 0x000000, 0xffffff, Widgets.FONTS.DejaVu18)

    current_mode_label = Widgets.Label(MODES[0], 8, 70, 1.0, 0x000000, 0xffffff, Widgets.FONTS.DejaVu18)
    input_label = Widgets.Label(">", 8, 98, 1.0, 0x000000, 0xffffff, Widgets.FONTS.DejaVu18)

    # --- 菜单 ---
    menu_height = 122
    options_menu = LcdOptionsMenu(35, 8, 200, menu_height, ACTIONS, title="Options")
    preset_list = LcdOptionsMenu(35, 8, 200, menu_height, PRESET_KEYS, title="Presets")

    kb = MatrixKeyboard()

    # 初始化显示
    output_lines = wrap_text_by_char(output_string, 25)
    update_output_display()


def translate():
    """翻译核心函数"""
    global input_string, last_morse_output, output_string, last_input_display_string
    global output_lines, output_scroll_top_line

    if input_string:
        # [优化] 缩短历史输入预览的长度，防止覆盖右上角提示
        last_input_display_string = f"In: {input_string[:18]}"
    else:
        last_input_display_string = ""
    last_input_label.setText(last_input_display_string)

    mode = MODES[current_mode_index]
    translated_text = ""
    if mode == "Text -> Morse":
        # [修正] 采用更健壮的逻辑生成莫斯码字符串，确保单词和字母间隔正确
        # 这可以防止在单词之间产生多余的空格，从而修复时序计算错误
        words = input_string.upper().split(' ')
        morse_words = []
        for word in words:
            if not word: continue
            letters = [CHAR_TO_MORSE.get(c, '?') for c in word]
            morse_words.append(" ".join(letters))
        translated_text = " / ".join(morse_words)
        last_morse_output = translated_text  # Store for playing
    elif mode == "Morse -> Text":
        morse_words = input_string.split('/')
        text_result = []
        for word in morse_words:
            letters = word.strip().split(' ')
            for code in letters:
                if code: text_result.append(MORSE_TO_CHAR.get(code, '?'))
            text_result.append(' ')
        translated_text = "".join(text_result).strip()
        last_morse_output = ""  # Can't play text

    output_lines = wrap_text_by_char(translated_text, 25)
    output_scroll_top_line = 0
    update_output_display()

    input_string = ""
    input_label.setText(">")


def play_morse():
    """播放莫斯电码声音，并提供视觉反馈"""
    global last_morse_output
    if not last_morse_output: return

    # --- [最终方案] 使用背光控制实现真正的瞬时闪烁 ---
    # 1. 准备屏幕内容 (一次性绘制)
    M5.Lcd.fillRect(0, 0, 240, 135, 0xffffff)  # 白色背景
    M5.Lcd.setTextColor(0x000000) # 黑色文字
    M5.Lcd.setTextSize(2)
    M5.Lcd.setCursor(10, 10)
    M5.Lcd.print("Playing:")
    M5.Lcd.setCursor(10, 30)
    demo_lines = wrap_text_by_char(last_morse_output, 38)
    for line in demo_lines:
        M5.Lcd.print(line)

    # 2. 循环播放，只控制背光和声音
    for symbol in last_morse_output:
        duration = 0
        pause = 0
        # [优化] 基于 10 WPM (每点120ms) 重新设定时序，并修复间隔逻辑
        # 1 WPM = 1200 / dot_length_ms
        dot_length = 120

        if symbol == '.':
            duration = dot_length
            pause = dot_length  # 元素内间隔: 1个点
        elif symbol == '-':
            duration = dot_length * 3
            pause = dot_length  # 元素内间隔: 1个点
        elif symbol == ' ':
            # 字母间额外停顿: 2个点 (总停顿 = 1 + 2 = 3个点)
            pause = dot_length * 2
        elif symbol == '/':
            # 单词间额外停顿: 4个点 (总停顿 = 3(字母间隔) + 4 = 7个点)
            pause = dot_length * 4

        if duration > 0:
            M5.Lcd.setBrightness(200)  # 背光开启 (使用一个柔和的亮度)
            if speaker_on:
                Speaker.tone(800, duration)

            time.sleep_ms(duration)

            M5.Lcd.setBrightness(0)    # 背光关闭

        time.sleep_ms(pause)

    # 3. 恢复UI和正常亮度
    M5.Lcd.setBrightness(100)  # 恢复到正常的亮度
    Widgets.fillScreen(0xffffff)
    force_all_widgets_redraw()


def handle_input():
    """处理所有键盘输入和功能逻辑"""
    global last_key_state, input_string, current_mode_index, speaker_on
    global is_menu_active, is_selecting_preset, output_scroll_top_line

    is_key_down = False
    try:
        kb.tick()
        is_key_down = kb.is_pressed()
    except Exception:
        pass

    if is_key_down and not last_key_state:
        key_string = kb.get_string()
        if key_string:
            if is_menu_active:
                action = options_menu.handle_key(key_string)
                if action:
                    is_menu_active = False
                    options_menu.hide()
                    restore_ui_after_menu_close(options_menu)

                    if action != 'close':
                        if action == "Switch Mode":
                            current_mode_index = (current_mode_index + 1) % len(MODES)
                            current_mode_label.setText(MODES[current_mode_index])
                        elif action == "Play Demo":
                            play_morse()
                        elif action == "Speaker":
                            speaker_on = not speaker_on
                        elif action == "Presets":
                            is_selecting_preset = True
                            preset_list.show()

            elif is_selecting_preset:
                preset = preset_list.handle_key(key_string)
                if preset:
                    is_selecting_preset = False
                    preset_list.hide()
                    restore_ui_after_menu_close(preset_list)

                    if preset != 'close':
                        # 根据当前模式决定将预设的文本还是莫斯码放入输入区
                        if MODES[current_mode_index] == "Text -> Morse":
                            input_string = preset  # 放入预设的文本 (key)
                        else: # Morse -> Text 模式
                            input_string = PRESETS.get(preset, "") # 放入预设的莫斯码 (value)
                        # This will be handled by the general input update below

            else:
                if key_string == '[':  # Scroll Up
                    if output_scroll_top_line > 0:
                        output_scroll_top_line -= 1
                        update_output_display()
                elif key_string == ']':  # Scroll Down
                    if output_scroll_top_line + 2 < len(output_lines):
                        output_scroll_top_line += 1
                        update_output_display()
                elif key_string == '\t':
                    is_menu_active = True
                    options_menu.show()
                elif key_string in ('enter', '\r','\n'):
                    translate()
                elif key_string == '\x08':  # Backspace
                    input_string = input_string[:-1]
                else:
                    input_string += key_string

            # [优化] 统一处理输入行显示，实现滚动效果
            if not is_menu_active and not is_selecting_preset:
                max_input_chars = 25  # 安全的单行字符数
                display_input = ">" + input_string
                if len(display_input) > max_input_chars:
                    display_input = ">" + input_string[-(max_input_chars - 1):]
                input_label.setText(display_input)

    last_key_state = is_key_down


def loop():
    M5.update()
    handle_input()

    if is_menu_active:
        options_menu.draw()
    elif is_selecting_preset:
        preset_list.draw()


if __name__ == '__main__':
    try:
        setup()
        while True:
            loop()
    except (Exception, KeyboardInterrupt) as e:
        print("--- A FATAL ERROR OCCURRED ---")
        sys.print_exception(e)
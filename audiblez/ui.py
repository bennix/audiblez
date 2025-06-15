#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# A simple wxWidgets UI for audiblez

import torch.cuda
import numpy as np
import soundfile
import threading
import platform
import subprocess
import io
import os
import time
import wx
from wx.lib.newevent import NewEvent
from wx.lib.scrolledpanel import ScrolledPanel
from PIL import Image
from tempfile import NamedTemporaryFile
from pathlib import Path

from audiblez.voices import voices, flags, flags_win # Import flags_win as well

EVENTS = {
    'CORE_STARTED': NewEvent(),
    'CORE_PROGRESS': NewEvent(),
    'CORE_CHAPTER_STARTED': NewEvent(),
    'CORE_CHAPTER_FINISHED': NewEvent(),
    'CORE_FINISHED': NewEvent()
}

border = 5


class MainWindow(wx.Frame):
    def __init__(self, parent, title):
        screen_width, screen_h = wx.GetDisplaySize()
        self.window_width = int(screen_width * 0.6)
        super().__init__(parent, title=title, size=(self.window_width, self.window_width * 3 // 4))
        self.chapters_panel = None
        self.preview_threads = []
        self.selected_chapter = None
        self.selected_book = None
        self.synthesis_in_progress = False
        self.selected_language_code = None
        self.selected_voice_name = None
        self.selected_speed = '1.0'

        # Ensure these are initialized to None
        self.book_info_panel_box = None
        self.params_panel_box = None
        self.synth_panel_box = None
        # These specific panel references might also need to be initialized if accessed before creation
        self.book_info_panel = None 
        self.params_panel = None
        self.synth_panel = None

        self.Bind(EVENTS['CORE_STARTED'][1], self.on_core_started)
        self.Bind(EVENTS['CORE_CHAPTER_STARTED'][1], self.on_core_chapter_started)
        self.Bind(EVENTS['CORE_CHAPTER_FINISHED'][1], self.on_core_chapter_finished)
        self.Bind(EVENTS['CORE_PROGRESS'][1], self.on_core_progress)
        self.Bind(EVENTS['CORE_FINISHED'][1], self.on_core_finished)

        self.create_menu()
        self.create_layout()
        self.Centre()
        self.Show(True)
        if Path('../epub/lewis.epub').exists(): self.open_epub('../epub/lewis.epub')

    def create_menu(self):
        menubar = wx.MenuBar()
        file_menu = wx.Menu()
        # Translate menu items
        open_item = wx.MenuItem(file_menu, wx.ID_OPEN, "打开(&O)\tCtrl+O")
        file_menu.Append(open_item)
        self.Bind(wx.EVT_MENU, self.on_open, open_item)  # Bind the event

        exit_item = wx.MenuItem(file_menu, wx.ID_EXIT, "退出(&X)\tCtrl+Q")
        file_menu.Append(exit_item)
        self.Bind(wx.EVT_MENU, self.on_exit, exit_item)

        menubar.Append(file_menu, "文件(&F)")
        self.SetMenuBar(menubar)

    def on_core_started(self, event):
        print('CORE_STARTED')
        self.progress_bar_label.Show()
        self.progress_bar.Show()
        self.progress_bar.SetValue(0)
        self.progress_bar.Layout()
        self.eta_label.Show()
        self.params_panel.Layout()
        self.synth_panel.Layout()

    def on_core_chapter_started(self, event):
        # print('CORE_CHAPTER_STARTED', event.chapter_index)
        self.set_table_chapter_status(event.chapter_index, "⏳ 进行中") # Translate status

    def on_core_chapter_finished(self, event):
        # print('CORE_CHAPTER_FINISHED', event.chapter_index)
        self.set_table_chapter_status(event.chapter_index, "✅ 完成") # Translate status
        self.start_button.Show()

    def on_core_progress(self, event):
        # print('CORE_PROGRESS', event.progress)
        self.progress_bar.SetValue(event.stats.progress)
        # Translate progress labels
        self.progress_bar_label.SetLabel(f"合成进度: {event.stats.progress}%")
        self.eta_label.SetLabel(f"预计剩余时间: {event.stats.eta}")
        self.synth_panel.Layout()

    def on_core_finished(self, event):
        self.synthesis_in_progress = False
        self.open_folder_with_explorer(self.output_folder_text_ctrl.GetValue())

    def create_layout(self):
        # Panels layout looks like this:
        # splitter
        #     notebook (tab control)
        #         tab1: 语言音色设置
        #         tab2: 章节列表 (only when EPUB is loaded)
        #     center_panel (when EPUB is loaded)
        #         text_area
        #     right_panel
        #         book_info_panel_box
        #         synth_panel_box

        top_panel = wx.Panel(self)
        top_sizer = wx.BoxSizer(wx.HORIZONTAL)
        top_panel.SetSizer(top_sizer)

        # Open Epub button - Translate button text
        open_epub_button = wx.Button(top_panel, label="📁 打开 EPUB")
        open_epub_button.Bind(wx.EVT_BUTTON, self.on_open)
        top_sizer.Add(open_epub_button, 0, wx.ALL, 5)

        # About button - Translate button text
        help_button = wx.Button(top_panel, label="ℹ️ 关于")
        help_button.Bind(wx.EVT_BUTTON, lambda event: self.about_dialog())
        top_sizer.Add(help_button, 0, wx.ALL, 5)

        self.main_sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(self.main_sizer)

        self.splitter = wx.Panel(self)
        self.splitter_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.splitter.SetSizer(self.splitter_sizer)

        self.main_sizer.Add(top_panel, 0, wx.ALL | wx.EXPAND, 5)
        self.main_sizer.Add(self.splitter, 1, wx.EXPAND)

        # 创建标签页控件
        self.create_notebook_panel()

    def create_notebook_panel(self):
        """创建包含标签页的面板"""
        self.notebook = wx.Notebook(self.splitter)
        
        # 第一个标签页：语言音色设置
        self.settings_panel = wx.Panel(self.notebook)
        self.notebook.AddPage(self.settings_panel, "🎵 语言音色设置")
        self.create_settings_tab_content()
        
        # 添加到主分割器
        self.splitter_sizer.Add(self.notebook, 1, wx.ALL | wx.EXPAND, 5)

    def create_settings_tab_content(self):
        """创建语言音色设置标签页的内容"""
        settings_sizer = wx.BoxSizer(wx.VERTICAL)
        self.settings_panel.SetSizer(settings_sizer)
        
        # 添加说明文本
        info_label = wx.StaticText(self.settings_panel, label="🎵 请选择语言和音色进行有声书制作")
        info_label.Wrap(300)
        font = info_label.GetFont()
        font.PointSize = 12
        info_label.SetFont(font)
        settings_sizer.Add(info_label, 0, wx.ALL | wx.EXPAND, 10)

        # 创建参数面板
        self.params_panel_box = wx.Panel(self.settings_panel, style=wx.SUNKEN_BORDER)
        params_panel_box_sizer = wx.StaticBoxSizer(wx.VERTICAL, self.params_panel_box, "有声书参数")
        self.params_panel_box.SetSizer(params_panel_box_sizer)
        settings_sizer.Add(self.params_panel_box, 1, wx.ALL | wx.EXPAND, 5)
        self.create_params_panel_content(self.params_panel_box)

    def about_dialog(self):
        # Translate about dialog message
        msg = ("一个使用 Kokoro-82M 模型从 EPUB 文件生成有声书的简单工具\n" +
               "根据 MIT 许可证分发。\n\n" +
               "by Claudio Santini 2025\nand many contributors.\n\n" +
               "https://claudio.uk\n\n")
        wx.MessageBox(msg, "Audiblez")



    def create_book_details_panel_content(self, parent_box):
        # parent_box is self.book_info_panel_box
        self.book_info_panel = wx.Panel(parent_box, style=wx.BORDER_NONE)
        self.book_info_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.book_info_panel.SetSizer(self.book_info_sizer)
        parent_box.GetSizer().Add(self.book_info_panel, 1, wx.ALL | wx.EXPAND, 5)

        # Add cover image
        self.cover_bitmap = wx.StaticBitmap(self.book_info_panel, -1)
        self.book_info_sizer.Add(self.cover_bitmap, 0, wx.ALL, 5)

        # Create the actual details panel (title, author, length)
        book_details_panel = wx.Panel(self.book_info_panel)
        book_details_sizer = wx.GridBagSizer(10, 10)
        book_details_panel.SetSizer(book_details_sizer)
        self.book_info_sizer.Add(book_details_panel, 1, wx.ALL | wx.EXPAND, 5)

        title_label = wx.StaticText(book_details_panel, label="书名:")
        title_text = wx.StaticText(book_details_panel, label=self.selected_book_title)
        book_details_sizer.Add(title_label, pos=(0, 0), flag=wx.ALL, border=5)
        book_details_sizer.Add(title_text, pos=(0, 1), flag=wx.ALL, border=5)

        author_label = wx.StaticText(book_details_panel, label="作者:")
        author_text = wx.StaticText(book_details_panel, label=self.selected_book_author)
        book_details_sizer.Add(author_label, pos=(1, 0), flag=wx.ALL, border=5)
        book_details_sizer.Add(author_text, pos=(1, 1), flag=wx.ALL, border=5)

        length_label = wx.StaticText(book_details_panel, label="总长度:")
        if not hasattr(self, 'document_chapters'):
            total_len = 0
        else:
            total_len = sum([len(c.extracted_text) for c in self.document_chapters])
        length_text = wx.StaticText(book_details_panel, label=f'{total_len:,} 字符')
        book_details_sizer.Add(length_label, pos=(2, 0), flag=wx.ALL, border=5)
        book_details_sizer.Add(length_text, pos=(2, 1), flag=wx.ALL, border=5)

        parent_box.Layout()

    def create_params_panel_content(self, parent_box):
        # parent_box is self.params_panel_box
        self.params_panel = wx.Panel(parent_box)
        parent_box.GetSizer().Add(self.params_panel, 1, wx.ALL | wx.EXPAND, 5)

        sizer = wx.GridBagSizer(10, 10)
        self.params_panel.SetSizer(sizer)

        # 引擎选择 - 添加 MPS 支持
        engine_label = wx.StaticText(self.params_panel, label="引擎:")
        engine_radio_panel = wx.Panel(self.params_panel)
        cpu_radio = wx.RadioButton(engine_radio_panel, label="CPU", style=wx.RB_GROUP)
        cuda_radio = wx.RadioButton(engine_radio_panel, label="CUDA")
        mps_radio = wx.RadioButton(engine_radio_panel, label="MPS")
        
        # 设置默认选择和可用性
        cuda_available = torch.cuda.is_available()
        mps_available = hasattr(torch.backends, 'mps') and torch.backends.mps.is_available()
        
        if cuda_available:
            cuda_radio.SetValue(True)
        elif mps_available:
            mps_radio.SetValue(True)
        else:
            cpu_radio.SetValue(True)
        
        # 禁用不可用的选项
        if not cuda_available:
            cuda_radio.Enable(False)
        if not mps_available:
            mps_radio.Enable(False)
            
        sizer.Add(engine_label, pos=(0, 0), flag=wx.ALL, border=border)
        sizer.Add(engine_radio_panel, pos=(0, 1), flag=wx.ALL, border=border)
        engine_radio_panel_sizer = wx.BoxSizer(wx.HORIZONTAL)
        engine_radio_panel.SetSizer(engine_radio_panel_sizer)
        engine_radio_panel_sizer.Add(cpu_radio, 0, wx.ALL, 5)
        engine_radio_panel_sizer.Add(cuda_radio, 0, wx.ALL, 5)
        engine_radio_panel_sizer.Add(mps_radio, 0, wx.ALL, 5)
        
        # 绑定事件处理器
        cpu_radio.Bind(wx.EVT_RADIOBUTTON, lambda event: torch.set_default_device('cpu'))
        cuda_radio.Bind(wx.EVT_RADIOBUTTON, lambda event: torch.set_default_device('cuda'))
        mps_radio.Bind(wx.EVT_RADIOBUTTON, lambda event: torch.set_default_device('mps'))

        # 语言选择 - 改进版本
        language_label = wx.StaticText(self.params_panel, label="语言:")
        
        # 创建更友好的语言名称映射
        language_names = {
            'a': '英语 (美式)',
            'b': '英语 (英式)', 
            'e': '西班牙语',
            'f': '法语',
            'h': '印地语',
            'i': '意大利语',
            'j': '日语',
            'p': '葡萄牙语',
            'z': '中文'
        }
        
        current_flags = flags_win if platform.system() == 'Windows' else flags
        # 生成格式：🇺🇸 英语 (美式)
        language_choices = [f"{current_flags.get(code, '')} {language_names.get(code, code)}" for code in voices.keys()]
        
        self.language_dropdown = wx.ComboBox(self.params_panel, choices=language_choices, style=wx.CB_READONLY)
        self.language_dropdown.Bind(wx.EVT_COMBOBOX, self.on_language_selected)
        sizer.Add(language_label, pos=(1, 0), flag=wx.ALL, border=border)
        sizer.Add(self.language_dropdown, pos=(1, 1), flag=wx.ALL | wx.EXPAND, border=border)

        # 语音选择
        voice_label = wx.StaticText(self.params_panel, label="语音:")
        self.voice_dropdown = wx.ComboBox(self.params_panel, choices=[], style=wx.CB_READONLY)
        self.voice_dropdown.Bind(wx.EVT_COMBOBOX, self.on_voice_selected)
        sizer.Add(voice_label, pos=(2, 0), flag=wx.ALL, border=border)
        sizer.Add(self.voice_dropdown, pos=(2, 1), flag=wx.ALL | wx.EXPAND, border=border)

        # 初始化语言和语音下拉框
        if language_choices:
            self.language_dropdown.SetValue(language_choices[0])
            # 手动触发事件以填充语音
            evt = wx.CommandEvent(wx.wxEVT_COMMAND_COMBOBOX_SELECTED, self.language_dropdown.GetId())
            evt.SetEventObject(self.language_dropdown)
            evt.SetString(self.language_dropdown.GetValue())
            wx.PostEvent(self.language_dropdown.GetEventHandler(), evt) # 发送到 ComboBox 的事件处理器
        else:
            # 如果没有语言选项，清空并禁用语音下拉框
            self.voice_dropdown.SetItems([])
            self.voice_dropdown.SetValue("")
            self.voice_dropdown.Disable()
            self.selected_language_code = None
            self.selected_voice_name = None

        # 语速选择
        speed_label = wx.StaticText(self.params_panel, label="语速:")
        self.speed_text_input = wx.TextCtrl(self.params_panel, value=self.selected_speed) # 使用 self.selected_speed 初始化
        self.speed_text_input.Bind(wx.EVT_TEXT, self.on_select_speed)
        sizer.Add(speed_label, pos=(3, 0), flag=wx.ALL, border=border)
        sizer.Add(self.speed_text_input, pos=(3, 1), flag=wx.ALL | wx.EXPAND, border=border)

        # 输出文件夹选择
        output_folder_label = wx.StaticText(self.params_panel, label="输出文件夹:")
        self.output_folder_text_ctrl = wx.TextCtrl(self.params_panel, value=os.path.abspath('.'))
        self.output_folder_text_ctrl.SetEditable(False)
        output_folder_button = wx.Button(self.params_panel, label="📂 选择")
        output_folder_button.Bind(wx.EVT_BUTTON, self.open_output_folder_dialog)
        sizer.Add(output_folder_label, pos=(4, 0), flag=wx.ALL, border=border)
        sizer.Add(self.output_folder_text_ctrl, pos=(4, 1), flag=wx.ALL | wx.EXPAND, border=border)
        sizer.Add(output_folder_button, pos=(5, 1), flag=wx.ALL, border=border)
        
        self.params_panel.Layout()
        self.params_panel_box.Layout()
        self.settings_panel.Layout()

    def create_synthesis_panel_content(self, parent_box):
        # parent_box is self.synth_panel_box
        panel = self.synth_panel = wx.Panel(parent_box)
        parent_box.GetSizer().Add(panel, 1, wx.ALL | wx.EXPAND, 5)
        sizer = wx.BoxSizer(wx.VERTICAL)
        panel.SetSizer(sizer)

        # Add Start button - Translate button label
        self.start_button = wx.Button(panel, label="🚀 开始合成有声书")
        self.start_button.Bind(wx.EVT_BUTTON, self.on_start)
        sizer.Add(self.start_button, 0, wx.ALL, 5)

        # Add Stop button
        # self.stop_button = wx.Button(panel, label="⏹️ Stop Synthesis")
        # self.stop_button.Bind(wx.EVT_BUTTON, self.on_stop)
        # sizer.Add(self.stop_button, 0, wx.ALL, 5)
        # self.stop_button.Hide()

        # Add Progress Bar label: - Translate label
        self.progress_bar_label = wx.StaticText(panel, label="合成进度:")
        sizer.Add(self.progress_bar_label, 0, wx.ALL, 5)
        self.progress_bar = wx.Gauge(panel, range=100, style=wx.GA_PROGRESS)
        self.progress_bar.SetMinSize((-1, 30))
        sizer.Add(self.progress_bar, 0, wx.ALL | wx.EXPAND, 5)
        self.progress_bar_label.Hide()
        self.progress_bar.Hide()

        # Add ETA Label - Translate label
        self.eta_label = wx.StaticText(panel, label="预计剩余时间: ")
        self.eta_label.Hide()
        sizer.Add(self.eta_label, 0, wx.ALL, 5)
        panel.Layout()
        parent_box.Layout()

    def open_output_folder_dialog(self, event):
        # Translate dialog title
        with wx.DirDialog(self, "选择一个文件夹:", style=wx.DD_DEFAULT_STYLE) as dialog:
            if dialog.ShowModal() == wx.ID_CANCEL:
                return
            output_folder = dialog.GetPath()
            print(f"选择的输出文件夹: {output_folder}") # Optional: translate print
            self.output_folder_text_ctrl.SetValue(output_folder)

    # New event handler for language selection
    def on_language_selected(self, event):
        selected_language_display = event.GetString()
        
        # 创建语言名称到代码的映射（用于反向查找）
        language_name_to_code = {
            '英语 (美式)': 'a',
            '英语 (英式)': 'b', 
            '西班牙语': 'e',
            '法语': 'f',
            '印地语': 'h',
            '意大利语': 'i',
            '日语': 'j',
            '葡萄牙语': 'p',
            '中文': 'z'
        }
        
        # 从显示文本中提取语言代码
        self.selected_language_code = None
        for lang_name, lang_code in language_name_to_code.items():
            if lang_name in selected_language_display:
                self.selected_language_code = lang_code
                break
        
        # 如果没有找到匹配的，尝试备用方法
        if not self.selected_language_code:
            # 尝试从格式中提取最后一个字符作为语言代码
            parts = selected_language_display.strip().split()
            if parts:
                last_part = parts[-1]
                if len(last_part) == 1 and last_part in voices:
                    self.selected_language_code = last_part

        if self.selected_language_code and self.selected_language_code in voices:
            voice_choices = voices[self.selected_language_code]
            self.voice_dropdown.Enable(True)
            
            # 创建带有描述的语音选项
            voice_descriptions = []
            for voice in voice_choices:
                # 从语音名称中提取性别和类型信息
                if voice.startswith('af_'):
                    desc = f"{voice} (女声)"
                elif voice.startswith('am_'):
                    desc = f"{voice} (男声)"
                elif voice.startswith('bf_'):
                    desc = f"{voice} (女声)"
                elif voice.startswith('bm_'):
                    desc = f"{voice} (男声)"
                elif voice.startswith('ef_'):
                    desc = f"{voice} (女声)"
                elif voice.startswith('em_'):
                    desc = f"{voice} (男声)"
                elif voice.startswith('ff_'):
                    desc = f"{voice} (女声)"
                elif voice.startswith('fm_'):
                    desc = f"{voice} (男声)"
                elif voice.startswith('hf_'):
                    desc = f"{voice} (女声)"
                elif voice.startswith('hm_'):
                    desc = f"{voice} (男声)"
                elif voice.startswith('if_'):
                    desc = f"{voice} (女声)"
                elif voice.startswith('im_'):
                    desc = f"{voice} (男声)"
                elif voice.startswith('jf_'):
                    desc = f"{voice} (女声)"
                elif voice.startswith('jm_'):
                    desc = f"{voice} (男声)"
                elif voice.startswith('pf_'):
                    desc = f"{voice} (女声)"
                elif voice.startswith('pm_'):
                    desc = f"{voice} (男声)"
                elif voice.startswith('zf_'):
                    desc = f"{voice} (女声)"
                elif voice.startswith('zm_'):
                    desc = f"{voice} (男声)"
                else:
                    desc = voice
                voice_descriptions.append(desc)
            
            self.voice_dropdown.SetItems(voice_descriptions)
            if voice_descriptions:
                self.voice_dropdown.SetValue(voice_descriptions[0])
                # 保存原始语音名称（不带描述）
                self.selected_voice_name = voice_choices[0]
            else:
                self.voice_dropdown.SetValue("")
                self.selected_voice_name = None
                self.voice_dropdown.Disable()
        else:
            self.voice_dropdown.SetItems([])
            self.voice_dropdown.SetValue("")
            self.voice_dropdown.Disable()
            self.selected_voice_name = None
            
        # 获取友好的语言名称用于显示
        code_to_language_name = {v: k for k, v in language_name_to_code.items()}
        friendly_name = code_to_language_name.get(self.selected_language_code, self.selected_language_code)
        
        print(f"语言已选择: {friendly_name}, 语音列表已更新, 当前选中语音: {self.selected_voice_name}")

    def on_voice_selected(self, event):
        selected_voice_display = event.GetString()
        
        # 从带描述的语音选择中提取原始语音名称
        # 格式如: "af_alloy (女声)" -> "af_alloy"
        if ' (' in selected_voice_display:
            self.selected_voice_name = selected_voice_display.split(' (')[0].strip()
        else:
            self.selected_voice_name = selected_voice_display.strip()
            
        print(f"语音已选择: {self.selected_voice_name}")

    def on_select_speed(self, event):
        try:
            speed_str = event.GetString()
            if speed_str:
                speed = float(speed_str)
                print('选择的语速', speed) # Optional: translate print
                self.selected_speed = speed
            else:
                self.selected_speed = 1.0 # Default if empty
        except ValueError:
            # Handle incorrect input, maybe show a message or revert to default
            print("无效的语速输入，使用默认值1.0") # Optional: translate print
            self.selected_speed = 1.0
            # Optionally, reset the text control to '1.0'
            # speed_text_input = event.GetEventObject()
            # speed_text_input.SetValue("1.0")

    def open_epub(self, file_path):
        # 如果已经有EPUB打开，清理之前的章节和书籍信息
        if hasattr(self, 'selected_book'):
            if hasattr(self, 'chapters_tab_panel') and self.chapters_tab_panel:
                # 移除章节标签页
                for page_idx in range(self.notebook.GetPageCount()):
                    if self.notebook.GetPageText(page_idx) == "📚 章节列表":
                        self.notebook.DeletePage(page_idx)
                        break
                self.chapters_tab_panel = None
            if hasattr(self, 'center_panel') and self.center_panel:
                self.center_panel.Destroy()
                self.center_panel = None
            # 清理之前的书籍信息和合成面板
            if hasattr(self, 'book_info_panel_box') and self.book_info_panel_box:
                self.book_info_panel_box.Destroy()
                self.book_info_panel_box = None
            if hasattr(self, 'synth_panel_box') and self.synth_panel_box:
                self.synth_panel_box.Destroy()
                self.synth_panel_box = None

        self.selected_file_path = file_path
        print(f"Opening file: {file_path}")

        from ebooklib import epub
        from audiblez.core import find_document_chapters_and_extract_texts, find_good_chapters, find_cover
        book = epub.read_epub(file_path)
        meta_title = book.get_metadata('DC', 'title')
        self.selected_book_title = meta_title[0][0] if meta_title else ''
        meta_creator = book.get_metadata('DC', 'creator')
        self.selected_book_author = meta_creator[0][0] if meta_creator else ''
        self.selected_book = book

        self.document_chapters = find_document_chapters_and_extract_texts(book)
        good_chapters = find_good_chapters(self.document_chapters)
        self.selected_chapter = good_chapters[0]
        for chapter in self.document_chapters:
            chapter.short_name = chapter.get_name().replace('.xhtml', '').replace('xhtml/', '').replace('.html', '').replace('Text/', '')
            chapter.is_selected = chapter in good_chapters

        # 创建EPUB界面布局
        self.create_layout_for_ebook()

        # 更新封面
        cover = find_cover(book)
        if cover is not None:
            pil_image = Image.open(io.BytesIO(cover.content))
            wx_img = wx.Image(pil_image.size[0], pil_image.size[1])
            wx_img.SetData(pil_image.convert("RGB").tobytes())
            cover_h = 200
            cover_w = int(cover_h * pil_image.size[0] / pil_image.size[1])
            wx_img.Rescale(cover_w, cover_h)
            self.cover_bitmap.SetBitmap(wx_img.ConvertToBitmap())
            self.cover_bitmap.SetMaxSize((200, cover_h))

        # 切换到章节列表标签页
        for page_idx in range(self.notebook.GetPageCount()):
            if self.notebook.GetPageText(page_idx) == "📚 章节列表":
                self.notebook.SetSelection(page_idx)
                break

        # 更新布局
        self.splitter.Layout()

    def create_layout_for_ebook(self):
        """为已打开的EPUB创建章节列表标签页和右侧面板"""
        # 创建章节列表标签页
        self.chapters_tab_panel = wx.Panel(self.notebook)
        self.notebook.AddPage(self.chapters_tab_panel, "📚 章节列表")
        self.create_chapters_tab_content()

        # 创建右侧的文本编辑和信息面板
        self.create_right_panels_for_ebook()

        # 更新设置标签页，添加书籍信息和合成状态
        self.update_settings_tab_for_ebook()

    def create_chapters_tab_content(self):
        """创建章节列表标签页的内容"""
        chapters_sizer = wx.BoxSizer(wx.VERTICAL)
        self.chapters_tab_panel.SetSizer(chapters_sizer)

        # 添加说明文本
        info_label = wx.StaticText(self.chapters_tab_panel, label="📚 选择要包含在有声书中的章节：")
        font = info_label.GetFont()
        font.PointSize = 12
        info_label.SetFont(font)
        chapters_sizer.Add(info_label, 0, wx.ALL, 10)

        # 创建章节表格
        from audiblez.core import find_good_chapters
        chapters_panel = self.create_chapters_table_panel(find_good_chapters(self.document_chapters))
        chapters_sizer.Add(chapters_panel, 1, wx.ALL | wx.EXPAND, 5)
        self.chapters_panel = chapters_panel

    def create_right_panels_for_ebook(self):
        """创建右侧的文本编辑面板"""
        # 创建文本编辑面板
        self.center_panel = wx.Panel(self.splitter)
        self.center_sizer = wx.BoxSizer(wx.VERTICAL)
        self.center_panel.SetSizer(self.center_sizer)
        
        self.text_area = wx.TextCtrl(self.center_panel, style=wx.TE_MULTILINE, size=(int(self.window_width * 0.4), -1))
        font = wx.Font(14, wx.MODERN, wx.NORMAL, wx.NORMAL)
        self.text_area.SetFont(font)
        self.text_area.Bind(wx.EVT_TEXT, lambda event: setattr(self.selected_chapter, 'extracted_text', self.text_area.GetValue()))

        self.chapter_label = wx.StaticText(
            self.center_panel, label=f'编辑/预览章节内容 "{self.selected_chapter.short_name}":')
        preview_button = wx.Button(self.center_panel, label="🔊 预览")
        preview_button.Bind(wx.EVT_BUTTON, self.on_preview_chapter)

        self.center_sizer.Add(self.chapter_label, 0, wx.ALL, 5)
        self.center_sizer.Add(preview_button, 0, wx.ALL, 5)
        self.center_sizer.Add(self.text_area, 1, wx.ALL | wx.EXPAND, 5)
        
        # 添加到主分割器
        self.splitter_sizer.Add(self.center_panel, 2, wx.ALL | wx.EXPAND, 5)

    def update_settings_tab_for_ebook(self):
        """为已打开的EPUB更新设置标签页，添加书籍信息和合成状态"""
        # 添加书籍信息面板
        self.book_info_panel_box = wx.Panel(self.settings_panel, style=wx.SUNKEN_BORDER)
        book_info_panel_box_sizer = wx.StaticBoxSizer(wx.VERTICAL, self.book_info_panel_box, "书籍详情")
        self.book_info_panel_box.SetSizer(book_info_panel_box_sizer)
        self.settings_panel.GetSizer().Insert(2, self.book_info_panel_box, 0, wx.ALL | wx.EXPAND, 5)
        self.create_book_details_panel_content(self.book_info_panel_box)

        # 添加合成状态面板
        self.synth_panel_box = wx.Panel(self.settings_panel, style=wx.SUNKEN_BORDER)
        synth_panel_box_sizer = wx.StaticBoxSizer(wx.VERTICAL, self.synth_panel_box, "有声书生成状态")
        self.synth_panel_box.SetSizer(synth_panel_box_sizer)
        self.settings_panel.GetSizer().Add(self.synth_panel_box, 0, wx.ALL | wx.EXPAND, 5)
        self.create_synthesis_panel_content(self.synth_panel_box)
        
        # 更新布局
        self.settings_panel.Layout()

    def on_table_checked(self, event):
        self.document_chapters[event.GetIndex()].is_selected = True

    def on_table_unchecked(self, event):
        self.document_chapters[event.GetIndex()].is_selected = False

    def on_table_selected(self, event):
        chapter = self.document_chapters[event.GetIndex()]
        print('Selected', event.GetIndex(), chapter.short_name)
        self.selected_chapter = chapter
        self.text_area.SetValue(chapter.extracted_text)
        self.chapter_label.SetLabel(f'Edit / Preview content for section "{chapter.short_name}":')

    def create_chapters_table_panel(self, good_chapters):
        panel = ScrolledPanel(self.chapters_tab_panel, -1, style=wx.TAB_TRAVERSAL | wx.SUNKEN_BORDER)
        sizer = wx.BoxSizer(wx.VERTICAL)
        panel.SetSizer(sizer)

        self.table = table = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        table.InsertColumn(0, "Included")
        table.InsertColumn(1, "Chapter Name")
        table.InsertColumn(2, "Chapter Length")
        table.InsertColumn(3, "Status")
        table.SetColumnWidth(0, 80)
        table.SetColumnWidth(1, 150)
        table.SetColumnWidth(2, 150)
        table.SetColumnWidth(3, 100)
        table.EnableCheckBoxes()
        table.Bind(wx.EVT_LIST_ITEM_CHECKED, self.on_table_checked)
        table.Bind(wx.EVT_LIST_ITEM_UNCHECKED, self.on_table_unchecked)
        table.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_table_selected)

        for i, chapter in enumerate(self.document_chapters):
            auto_selected = chapter in good_chapters
            table.Append(['', chapter.short_name, f"{len(chapter.extracted_text):,}"])
            if auto_selected: table.CheckItem(i)

        sizer.Add(table, 1, wx.ALL | wx.EXPAND, 5)
        return panel

    def get_selected_voice(self):
        # 直接返回 self.selected_voice_name，它应该已经是纯语音名
        if self.selected_voice_name:
            return self.selected_voice_name
        # 如果没有选择，可以返回一个默认值或 None
        # 尝试从 voices 字典中获取默认语言的第一个声音作为后备
        if self.selected_language_code and self.selected_language_code in voices and voices[self.selected_language_code]:
            return voices[self.selected_language_code][0]
        return None

    def get_selected_speed(self):
        try:
            return float(self.selected_speed)
        except ValueError:
            return 1.0 # 默认语速

    def on_preview_chapter(self, event):
        if not self.selected_language_code or not self.get_selected_voice():
            wx.MessageBox("请先选择语言和语音。", "提示", wx.OK | wx.ICON_WARNING)
            return

        lang_code = self.selected_language_code
        voice_name = self.get_selected_voice()

        if not voice_name:
            wx.MessageBox("未能获取有效语音，请重新选择。", "提示", wx.OK | wx.ICON_WARNING)
            return

        button = event.GetEventObject()
        button.SetLabel("⏳ 生成中...")
        button.Disable()

        def generate_preview():
            try:
                import audiblez.core as core
                from kokoro import KPipeline
                pipeline = KPipeline(lang_code=lang_code)
                core.load_spacy()
                
                # 增加预览文本长度 - 取前1500个字符（约2-3分钟音频）
                full_text = self.selected_chapter.extracted_text
                preview_text = full_text[:1500] if len(full_text) > 1500 else full_text
                
                if len(preview_text.strip()) == 0: 
                    wx.CallAfter(wx.MessageBox, "所选章节内容为空，无法预览。", "提示", wx.OK | wx.ICON_WARNING)
                    wx.CallAfter(button.SetLabel, "🔊 预览")
                    wx.CallAfter(button.Enable)
                    return
                
                # 生成音频
                audio_segments = core.gen_audio_segments(
                    pipeline,
                    preview_text,
                    voice=voice_name,
                    speed=self.get_selected_speed())
                final_audio = np.concatenate(audio_segments)
                
                # 创建临时文件
                tmp_preview_wav_file = NamedTemporaryFile(suffix='.wav', delete=False)
                soundfile.write(tmp_preview_wav_file.name, final_audio, core.sample_rate)
                
                # 在UI线程中创建预览窗口
                wx.CallAfter(self.show_preview_window, tmp_preview_wav_file.name, preview_text, voice_name)
                
            except Exception as e:
                wx.CallAfter(wx.MessageBox, f"预览生成失败: {str(e)}", "错误", wx.OK | wx.ICON_ERROR)
            finally:
                wx.CallAfter(button.SetLabel, "🔊 预览")
                wx.CallAfter(button.Enable)

        if len(self.preview_threads) > 0:
            for thread in self.preview_threads:
                thread.join()
            self.preview_threads = []
        thread = threading.Thread(target=generate_preview)
        thread.start()
        self.preview_threads.append(thread)

    def show_preview_window(self, audio_file_path, preview_text, voice_name):
        """显示音频预览窗口，包含播放控制和下载功能"""
        preview_dialog = AudioPreviewDialog(self, audio_file_path, preview_text, voice_name)
        preview_dialog.Show()

    def on_start(self, event):
        self.synthesis_in_progress = True
        file_path = self.selected_file_path
        
        if not self.selected_language_code or not self.get_selected_voice(): # 使用 get_selected_voice()
            wx.MessageBox("请先选择语言和语音再开始合成。", "提示", wx.OK | wx.ICON_WARNING)
            self.start_button.Enable()
            self.synthesis_in_progress = False # 重置状态
            return

        voice = self.get_selected_voice() # 使用 get_selected_voice()
        if not voice: # 再次检查 voice 是否有效
            wx.MessageBox("未能获取有效语音用于合成，请重新选择。", "提示", wx.OK | wx.ICON_WARNING)
            self.start_button.Enable()
            self.synthesis_in_progress = False # 重置状态
            return

        speed = self.get_selected_speed()
        selected_chapters = [chapter for chapter in self.document_chapters if chapter.is_selected]
        self.start_button.Disable()
        self.params_panel.Disable()

        self.table.EnableCheckBoxes(False)
        for chapter_index, chapter in enumerate(self.document_chapters):
            if chapter in selected_chapters:
                self.set_table_chapter_status(chapter_index, "Planned")
                self.table.SetItem(chapter_index, 0, '✔️')

        # self.stop_button.Show()
        print('Starting Audiobook Synthesis', dict(file_path=file_path, voice=voice, pick_manually=False, speed=speed))
        self.core_thread = CoreThread(params=dict(
            file_path=file_path, voice=voice, pick_manually=False, speed=speed,
            output_folder=self.output_folder_text_ctrl.GetValue(),
            selected_chapters=selected_chapters))
        self.core_thread.start()

    def on_open(self, event):
        with wx.FileDialog(self, "Open EPUB File", wildcard="*.epub", style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() == wx.ID_CANCEL:
                return
            file_path = dialog.GetPath()
            print(f"Selected file: {file_path}")
            if not file_path:
                print('No filepath?')
                return
            if self.synthesis_in_progress:
                wx.MessageBox("Audiobook synthesis is still in progress. Please wait for it to finish.", "Audiobook Synthesis in Progress")
            else:
                wx.CallAfter(self.open_epub, file_path)

    def on_exit(self, event):
        self.Close()

    def set_table_chapter_status(self, chapter_index, status):
        self.table.SetItem(chapter_index, 3, status)

    def open_folder_with_explorer(self, folder_path):
        try:
            if platform.system() == 'Windows':
                subprocess.Popen(['explorer', folder_path])
            elif platform.system() == 'Linux':
                subprocess.Popen(['xdg-open', folder_path])
            elif platform.system() == 'Darwin':
                subprocess.Popen(['open', folder_path])
        except Exception as e:
            print(e)


class CoreThread(threading.Thread):
    def __init__(self, params):
        super().__init__()
        self.params = params

    def run(self):
        import core
        core.main(**self.params, post_event=self.post_event)

    def post_event(self, event_name, **kwargs):
        # eg. 'EVENT_CORE_PROGRESS' -> EventCoreProgress, EVENT_CORE_PROGRESS
        EventObject, EVENT_CODE = EVENTS[event_name]
        event_object = EventObject()
        for k, v in kwargs.items():
            setattr(event_object, k, v)
        wx.PostEvent(wx.GetApp().GetTopWindow(), event_object)


class AudioPreviewDialog(wx.Frame):
    def __init__(self, parent, audio_file_path, preview_text, voice_name):
        super().__init__(parent, title="🔊 音频预览", size=(600, 500))
        self.audio_file_path = audio_file_path
        self.preview_text = preview_text
        self.voice_name = voice_name
        self.audio_process = None
        self.audio_duration = 0
        self.is_playing = False
        self.is_paused = False
        self.current_position = 0
        self.timer = wx.Timer(self)
        
        self.create_ui()
        self.get_audio_duration()
        self.Bind(wx.EVT_TIMER, self.update_progress)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        
        # 居中显示
        self.CenterOnParent()
        
    def create_ui(self):
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        panel.SetSizer(main_sizer)
        
        # 预览信息
        info_sizer = wx.BoxSizer(wx.HORIZONTAL)
        info_label = wx.StaticText(panel, label=f"语音: {self.voice_name}")
        info_label.SetFont(wx.Font(12, wx.MODERN, wx.NORMAL, wx.BOLD))
        info_sizer.Add(info_label, 0, wx.ALL, 5)
        main_sizer.Add(info_sizer, 0, wx.ALL | wx.EXPAND, 5)
        
        # 预览文本
        text_label = wx.StaticText(panel, label="预览文本内容:")
        text_label.SetFont(wx.Font(10, wx.MODERN, wx.NORMAL, wx.BOLD))
        main_sizer.Add(text_label, 0, wx.ALL, 5)
        
        self.text_ctrl = wx.TextCtrl(panel, value=self.preview_text, 
                                   style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP)
        self.text_ctrl.SetFont(wx.Font(10, wx.MODERN, wx.NORMAL, wx.NORMAL))
        main_sizer.Add(self.text_ctrl, 1, wx.ALL | wx.EXPAND, 5)
        
        # 播放控制区域
        control_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # 进度条
        progress_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.time_label = wx.StaticText(panel, label="00:00")
        self.progress_slider = wx.Slider(panel, value=0, minValue=0, maxValue=100, 
                                       style=wx.SL_HORIZONTAL | wx.SL_LABELS)
        self.duration_label = wx.StaticText(panel, label="00:00")
        
        progress_sizer.Add(self.time_label, 0, wx.ALL | wx.CENTER, 5)
        progress_sizer.Add(self.progress_slider, 1, wx.ALL | wx.EXPAND, 5)
        progress_sizer.Add(self.duration_label, 0, wx.ALL | wx.CENTER, 5)
        control_sizer.Add(progress_sizer, 0, wx.ALL | wx.EXPAND, 5)
        
        # 播放按钮
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.play_button = wx.Button(panel, label="▶️ 播放")
        self.stop_button = wx.Button(panel, label="⏹️ 停止")
        self.download_button = wx.Button(panel, label="💾 下载音频")
        
        self.play_button.Bind(wx.EVT_BUTTON, self.on_play)
        self.stop_button.Bind(wx.EVT_BUTTON, self.on_stop)
        self.download_button.Bind(wx.EVT_BUTTON, self.on_download)
        self.progress_slider.Bind(wx.EVT_SLIDER, self.on_seek)
        
        button_sizer.Add(self.play_button, 0, wx.ALL, 5)
        button_sizer.Add(self.stop_button, 0, wx.ALL, 5)
        button_sizer.Add(self.download_button, 0, wx.ALL, 5)
        control_sizer.Add(button_sizer, 0, wx.ALL | wx.CENTER, 5)
        
        main_sizer.Add(control_sizer, 0, wx.ALL | wx.EXPAND, 5)
        
        # 关闭按钮
        close_button = wx.Button(panel, label="关闭")
        close_button.Bind(wx.EVT_BUTTON, lambda event: self.Close())
        main_sizer.Add(close_button, 0, wx.ALL | wx.CENTER, 5)
        
    def get_audio_duration(self):
        """获取音频时长"""
        try:
            import subprocess
            cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'compact=print_section=0:nokey=1:escape=csv', 
                   '-show_entries', 'format=duration', self.audio_file_path]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                self.audio_duration = float(result.stdout.strip())
                self.duration_label.SetLabel(self.format_time(self.audio_duration))
                self.progress_slider.SetMax(int(self.audio_duration))
        except Exception as e:
            print(f"获取音频时长失败: {e}")
            self.audio_duration = 0
    
    def format_time(self, seconds):
        """将秒数格式化为 MM:SS"""
        minutes = int(seconds // 60)
        seconds = int(seconds % 60)
        return f"{minutes:02d}:{seconds:02d}"
    
    def on_play(self, event):
        """播放/暂停音频"""
        if not self.is_playing and not self.is_paused:
            # 开始播放
            self.start_playback(0)
        elif self.is_playing and not self.is_paused:
            # 暂停播放
            self.pause_playback()
        elif self.is_paused:
            # 恢复播放
            self.resume_playback()
    
    def start_playback(self, start_position=0):
        """开始播放音频"""
        try:
            if start_position > 0:
                cmd = ['ffplay', '-nodisp', '-autoexit', '-ss', str(start_position), self.audio_file_path]
            else:
                cmd = ['ffplay', '-nodisp', '-autoexit', self.audio_file_path]
            
            self.audio_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.is_playing = True
            self.is_paused = False
            self.play_button.SetLabel("⏸️ 暂停")
            self.timer.Start(1000)  # 每秒更新一次进度
            self.start_time = time.time() - start_position
            self.current_position = start_position
        except Exception as e:
            wx.MessageBox(f"播放失败: {str(e)}", "错误", wx.OK | wx.ICON_ERROR)
    
    def pause_playback(self):
        """暂停播放"""
        if self.audio_process:
            self.audio_process.terminate()
            self.audio_process = None
        
        self.is_playing = False
        self.is_paused = True
        self.play_button.SetLabel("▶️ 播放")
        self.timer.Stop()
        
        # 记录当前播放位置
        self.current_position = time.time() - self.start_time
        if self.current_position < 0:
            self.current_position = 0
        elif self.current_position > self.audio_duration:
            self.current_position = self.audio_duration
    
    def resume_playback(self):
        """恢复播放"""
        self.start_playback(self.current_position)
    
    def on_stop(self, event):
        """停止播放"""
        if self.audio_process:
            self.audio_process.terminate()
            self.audio_process = None
        self.is_playing = False
        self.is_paused = False
        self.current_position = 0
        self.play_button.SetLabel("▶️ 播放")
        self.timer.Stop()
        self.progress_slider.SetValue(0)
        self.time_label.SetLabel("00:00")
    
    def on_seek(self, event):
        """进度条拖动"""
        seek_time = self.progress_slider.GetValue()
        self.current_position = seek_time
        
        if self.is_playing:
            # 如果正在播放，停止当前播放并从新位置开始
            if self.audio_process:
                self.audio_process.terminate()
            self.start_playback(seek_time)
        elif self.is_paused:
            # 如果暂停中，只更新位置，不开始播放
            self.time_label.SetLabel(self.format_time(seek_time))
    
    def on_download(self, event):
        """下载音频文件"""
        with wx.FileDialog(self, "保存音频文件", 
                          defaultFile=f"preview_{self.voice_name}.wav",
                          wildcard="WAV文件 (*.wav)|*.wav",
                          style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                save_path = dialog.GetPath()
                try:
                    import shutil
                    shutil.copy2(self.audio_file_path, save_path)
                    wx.MessageBox(f"音频已保存至: {save_path}", "下载完成", wx.OK | wx.ICON_INFORMATION)
                except Exception as e:
                    wx.MessageBox(f"下载失败: {str(e)}", "错误", wx.OK | wx.ICON_ERROR)
    
    def update_progress(self, event):
        """更新播放进度"""
        if self.is_playing and self.audio_process:
            # 检查进程是否还在运行
            if self.audio_process.poll() is not None:
                # 播放结束
                self.on_stop(None)
                return
            
            # 计算播放时间
            current_time = time.time() - self.start_time
            if current_time >= 0 and current_time <= self.audio_duration:
                self.progress_slider.SetValue(int(current_time))
                self.time_label.SetLabel(self.format_time(current_time))
                self.current_position = current_time
            elif current_time > self.audio_duration:
                self.on_stop(None)
    
    def on_close(self, event):
        """关闭窗口时清理资源"""
        self.on_stop(None)
        # 删除临时文件
        try:
            os.unlink(self.audio_file_path)
        except:
            pass
        event.Skip()


def main():
    print('Starting GUI...')
    app = wx.App(False)
    frame = MainWindow(None, "Audiblez - Generate Audiobooks from E-books")
    frame.Show(True)
    frame.Layout()
    app.SetTopWindow(frame)
    print('Done.')
    app.MainLoop()


if __name__ == '__main__':
    main()

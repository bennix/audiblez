# ... existing code ...

class MainWindow(wx.Frame):
    # ... existing code ...

    def create_right_panel(self, parent_panel):
        # ... existing code ...
        self.params_panel = wx.Panel(self.params_panel_box)
        params_sizer = wx.BoxSizer(wx.VERTICAL)

        # --- 语言选择 --- 
        language_label = wx.StaticText(self.params_panel, label="选择语言:")
        params_sizer.Add(language_label, 0, wx.ALL, border)

        # 获取语言选项，例如从 voices.py 的 flags
        self.language_choices = [] # 例如：["🇨🇳 中文", "🇺🇸 American English", ...]
        self.language_map = {} # 例如：{"🇨🇳 中文": "z", "🇺🇸 American English": "a", ...}
        # ... 填充 self.language_choices 和 self.language_map ...
        for lang_code, lang_name_or_flag in flags.items(): # 假设 flags 适合直接显示
            # 根据操作系统选择合适的显示名称
            display_name = f"{flags.get(lang_code, lang_code)} {lang_code}" # 简单示例
            self.language_choices.append(display_name)
            self.language_map[display_name] = lang_code

        self.language_choice_ctrl = wx.Choice(self.params_panel, choices=self.language_choices)
        self.language_choice_ctrl.Bind(wx.EVT_CHOICE, self.on_language_selected)
        params_sizer.Add(self.language_choice_ctrl, 0, wx.ALL | wx.EXPAND, border)

        # --- 语音类型选择 (依赖于语言选择) ---
        voice_label = wx.StaticText(self.params_panel, label="选择语音:")
        params_sizer.Add(voice_label, 0, wx.ALL, border)
        self.voice_choice_ctrl = wx.Choice(self.params_panel, choices=[]) # 初始为空
        params_sizer.Add(self.voice_choice_ctrl, 0, wx.ALL | wx.EXPAND, border)
        # ... 其他参数如 speed, cuda, output folder ...

        # 初始化语音列表 (例如默认选择第一个语言)
        if self.language_choices:
            self.language_choice_ctrl.SetStringSelection(self.language_choices[0])
            self.on_language_selected(None) # 手动触发一次以填充语音列表

        self.params_panel.SetSizer(params_sizer)
        # ... existing code ...

    def on_language_selected(self, event):
        selected_language_display_name = self.language_choice_ctrl.GetStringSelection()
        selected_lang_code = self.language_map.get(selected_language_display_name)

        if selected_lang_code:
            available_voices_for_lang = voices.get(selected_lang_code, [])
            self.voice_choice_ctrl.Clear()
            self.voice_choice_ctrl.AppendItems(available_voices_for_lang)
            if available_voices_for_lang:
                self.voice_choice_ctrl.SetSelection(0) # 默认选择第一个语音
        else:
            self.voice_choice_ctrl.Clear()

    def get_selected_voice(self):
        # 这个方法需要在开始合成时被调用，以获取最终选择的语音
        return self.voice_choice_ctrl.GetStringSelection()

    # 在 on_start_synthesis 或类似的方法中，使用 self.get_selected_voice() 获取语音参数
    # ... existing code ...
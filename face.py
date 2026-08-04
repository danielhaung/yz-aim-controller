import tkinter as tk
import random
import math

class Face:
    def __init__(self):
        self.window = tk.Tk()
        self.window.attributes('-fullscreen', True)
        self.skin_color = '#F2C9A5'
        self.window.configure(bg=self.skin_color)
        self.window.bind('<Escape>', lambda e: self.window.destroy())
        
        self.canvas = tk.Canvas(self.window, bg=self.skin_color, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        
        self.expressions = ['happy', 'angry', 'sad', 'joy', 'surprise', 'fear', 'disgust', 'neutral', 'crying', 'winking', 'sleeping', 'laughing']
        # 啟動時優先使用笑臉，眼睛與嘴巴保持同一種表情。
        startup_expressions = ['happy', 'happy', 'joy', 'laughing', 'winking', 'neutral']
        self.current_expression = random.choice(startup_expressions)
        self.current_eye_expression = self.current_expression
        
        self.center_x = None
        self.center_y = None
        self.face_radius = None
        
        self.eye_angle = 0
        self.mouth_animation_frame = 0
        self.blink_timer = 0
        self.is_blinking = False
        
        self.window.bind('<Configure>', self.on_resize)
        self.draw_face()
        self.start_eye_animation()
        self.start_mouth_animation()
        self.update_expression()
        
    def on_resize(self, event):
        self.center_x = event.width // 2
        self.center_y = event.height // 2

        # 不再用圓形頭部半徑，而是用螢幕短邊作為表情縮放基準。
        # 0.92 讓五官幾乎占滿整個畫面，同時保留少量邊界。
        self.face_radius = int(min(event.width, event.height) * 0.92)
        self.draw_face()
        
    def draw_face(self):
        self.canvas.delete('all')
        
        if self.center_x is None:
            width = max(self.window.winfo_width(), 1)
            height = max(self.window.winfo_height(), 1)
            self.center_x = width // 2
            self.center_y = height // 2
            self.face_radius = int(min(width, height) * 0.92)

        width = max(self.canvas.winfo_width(), 1)
        height = max(self.canvas.winfo_height(), 1)
        scale = min(width, height)
        self.feature_line_width = max(7, int(scale * 0.012))
        self.nose_line_width = max(9, int(scale * 0.016))

        # 全螢幕臉部：不畫圓形頭部，使用膚色背景與放大的五官。
        eye_y = height * 0.30
        eye_offset = width * 0.19
        eye_radius = scale * 0.105
        
        self.left_eye_center = (self.center_x - eye_offset, eye_y)
        self.right_eye_center = (self.center_x + eye_offset, eye_y)
        self.eye_radius = eye_radius
        
        self.draw_eyes()
        
        nose_y = height * 0.52
        self.canvas.create_line(
            self.center_x, nose_y - scale * 0.055,
            self.center_x, nose_y + scale * 0.055,
            fill='black', width=self.nose_line_width
        )
        
        self.mouth_y = height * 0.70
        self.draw_mouth()
        
    def draw_eyes(self):
        expr = self.current_eye_expression
        eye_r = self.eye_radius
        
        if self.is_blinking:
            self.canvas.create_line(
                self.left_eye_center[0] - eye_r * 1.5, self.left_eye_center[1],
                self.left_eye_center[0] + eye_r * 1.5, self.left_eye_center[1],
                fill='black', width=3
            )
            self.canvas.create_line(
                self.right_eye_center[0] - eye_r * 1.5, self.right_eye_center[1],
                self.right_eye_center[0] + eye_r * 1.5, self.right_eye_center[1],
                fill='black', width=3
            )
            return
            
        if expr == 'happy':
            self.canvas.create_oval(
                self.left_eye_center[0] - eye_r, self.left_eye_center[1] - eye_r * 0.5,
                self.left_eye_center[0] + eye_r, self.left_eye_center[1] + eye_r * 0.5,
                fill='black'
            )
            self.canvas.create_oval(
                self.right_eye_center[0] - eye_r, self.right_eye_center[1] - eye_r * 0.5,
                self.right_eye_center[0] + eye_r, self.right_eye_center[1] + eye_r * 0.5,
                fill='black'
            )
        elif expr == 'angry':
            self.canvas.create_line(
                self.left_eye_center[0] - eye_r * 1.5, self.left_eye_center[1] - eye_r,
                self.left_eye_center[0] + eye_r * 1.5, self.left_eye_center[1] + eye_r,
                fill='black', width=4
            )
            self.canvas.create_line(
                self.right_eye_center[0] - eye_r * 1.5, self.right_eye_center[1] + eye_r,
                self.right_eye_center[0] + eye_r * 1.5, self.right_eye_center[1] - eye_r,
                fill='black', width=4
            )
            self.canvas.create_oval(
                self.left_eye_center[0] - eye_r, self.left_eye_center[1] - eye_r,
                self.left_eye_center[0] + eye_r, self.left_eye_center[1] + eye_r,
                fill='white', outline='black', width=2
            )
            self.canvas.create_oval(
                self.right_eye_center[0] - eye_r, self.right_eye_center[1] - eye_r,
                self.right_eye_center[0] + eye_r, self.right_eye_center[1] + eye_r,
                fill='white', outline='black', width=2
            )
            self.draw_pupils()
        elif expr == 'sad':
            self.canvas.create_oval(
                self.left_eye_center[0] - eye_r, self.left_eye_center[1] - eye_r,
                self.left_eye_center[0] + eye_r, self.left_eye_center[1] + eye_r,
                fill='white', outline='black', width=2
            )
            self.canvas.create_oval(
                self.right_eye_center[0] - eye_r, self.right_eye_center[1] - eye_r,
                self.right_eye_center[0] + eye_r, self.right_eye_center[1] + eye_r,
                fill='white', outline='black', width=2
            )
            self.canvas.create_oval(
                self.left_eye_center[0] - eye_r * 0.3, self.left_eye_center[1] + eye_r * 0.2,
                self.left_eye_center[0] + eye_r * 0.3, self.left_eye_center[1] + eye_r * 0.8,
                fill='black'
            )
            self.canvas.create_oval(
                self.right_eye_center[0] - eye_r * 0.3, self.right_eye_center[1] + eye_r * 0.2,
                self.right_eye_center[0] + eye_r * 0.3, self.right_eye_center[1] + eye_r * 0.8,
                fill='black'
            )
        elif expr == 'joy':
            self.canvas.create_oval(
                self.left_eye_center[0] - eye_r, self.left_eye_center[1] - eye_r,
                self.left_eye_center[0] + eye_r, self.left_eye_center[1] + eye_r,
                fill='black'
            )
            self.canvas.create_oval(
                self.right_eye_center[0] - eye_r, self.right_eye_center[1] - eye_r,
                self.right_eye_center[0] + eye_r, self.right_eye_center[1] + eye_r,
                fill='black'
            )
        elif expr == 'surprise':
            self.canvas.create_oval(
                self.left_eye_center[0] - eye_r * 1.2, self.left_eye_center[1] - eye_r * 1.2,
                self.left_eye_center[0] + eye_r * 1.2, self.left_eye_center[1] + eye_r * 1.2,
                fill='white', outline='black', width=2
            )
            self.canvas.create_oval(
                self.right_eye_center[0] - eye_r * 1.2, self.right_eye_center[1] - eye_r * 1.2,
                self.right_eye_center[0] + eye_r * 1.2, self.right_eye_center[1] + eye_r * 1.2,
                fill='white', outline='black', width=2
            )
            self.draw_pupils()
        elif expr == 'fear':
            self.canvas.create_oval(
                self.left_eye_center[0] - eye_r, self.left_eye_center[1] - eye_r,
                self.left_eye_center[0] + eye_r, self.left_eye_center[1] + eye_r,
                fill='white', outline='black', width=2
            )
            self.canvas.create_oval(
                self.right_eye_center[0] - eye_r, self.right_eye_center[1] - eye_r,
                self.right_eye_center[0] + eye_r, self.right_eye_center[1] + eye_r,
                fill='white', outline='black', width=2
            )
            self.canvas.create_oval(
                self.left_eye_center[0] - eye_r * 0.2, self.left_eye_center[1] - eye_r * 0.5,
                self.left_eye_center[0] + eye_r * 0.2, self.left_eye_center[1] + eye_r * 0.2,
                fill='black'
            )
            self.canvas.create_oval(
                self.right_eye_center[0] - eye_r * 0.2, self.right_eye_center[1] - eye_r * 0.5,
                self.right_eye_center[0] + eye_r * 0.2, self.right_eye_center[1] + eye_r * 0.2,
                fill='black'
            )
            self.canvas.create_oval(
                self.left_eye_center[0] - eye_r * 0.1, self.left_eye_center[1] + eye_r * 0.3,
                self.left_eye_center[0] + eye_r * 0.5, self.left_eye_center[1] + eye_r * 0.5,
                fill='white'
            )
            self.canvas.create_oval(
                self.right_eye_center[0] - eye_r * 0.1, self.right_eye_center[1] + eye_r * 0.3,
                self.right_eye_center[0] + eye_r * 0.5, self.right_eye_center[1] + eye_r * 0.5,
                fill='white'
            )
        elif expr == 'disgust':
            self.canvas.create_line(
                self.left_eye_center[0] - eye_r * 1.5, self.left_eye_center[1],
                self.left_eye_center[0] + eye_r * 1.5, self.left_eye_center[1] + eye_r * 0.5,
                fill='black', width=4
            )
            self.canvas.create_line(
                self.right_eye_center[0] - eye_r * 1.5, self.right_eye_center[1],
                self.right_eye_center[0] + eye_r * 1.5, self.right_eye_center[1] + eye_r * 0.5,
                fill='black', width=4
            )
            self.canvas.create_oval(
                self.left_eye_center[0] - eye_r, self.left_eye_center[1] - eye_r,
                self.left_eye_center[0] + eye_r, self.left_eye_center[1] + eye_r,
                fill='white', outline='black', width=2
            )
            self.canvas.create_oval(
                self.right_eye_center[0] - eye_r, self.right_eye_center[1] - eye_r,
                self.right_eye_center[0] + eye_r, self.right_eye_center[1] + eye_r,
                fill='white', outline='black', width=2
            )
            self.draw_pupils()
        elif expr == 'neutral':
            self.canvas.create_oval(
                self.left_eye_center[0] - eye_r, self.left_eye_center[1] - eye_r,
                self.left_eye_center[0] + eye_r, self.left_eye_center[1] + eye_r,
                fill='white', outline='black', width=2
            )
            self.canvas.create_oval(
                self.right_eye_center[0] - eye_r, self.right_eye_center[1] - eye_r,
                self.right_eye_center[0] + eye_r, self.right_eye_center[1] + eye_r,
                fill='white', outline='black', width=2
            )
            self.draw_pupils()
        elif expr == 'crying':
            self.canvas.create_oval(
                self.left_eye_center[0] - eye_r, self.left_eye_center[1] - eye_r,
                self.left_eye_center[0] + eye_r, self.left_eye_center[1] + eye_r,
                fill='white', outline='black', width=2
            )
            self.canvas.create_oval(
                self.right_eye_center[0] - eye_r, self.right_eye_center[1] - eye_r,
                self.right_eye_center[0] + eye_r, self.right_eye_center[1] + eye_r,
                fill='white', outline='black', width=2
            )
            self.canvas.create_oval(
                self.left_eye_center[0] - eye_r * 0.3, self.left_eye_center[1] - eye_r * 0.2,
                self.left_eye_center[0] + eye_r * 0.3, self.left_eye_center[1] + eye_r * 0.3,
                fill='black'
            )
            self.canvas.create_oval(
                self.right_eye_center[0] - eye_r * 0.3, self.right_eye_center[1] - eye_r * 0.2,
                self.right_eye_center[0] + eye_r * 0.3, self.right_eye_center[1] + eye_r * 0.3,
                fill='black'
            )
            tear_size = eye_r * 0.8 + math.sin(self.mouth_animation_frame * 0.2) * eye_r * 0.2
            self.canvas.create_oval(
                self.left_eye_center[0] + eye_r * 0.5, self.left_eye_center[1] + eye_r * 0.3,
                self.left_eye_center[0] + eye_r * 0.8, self.left_eye_center[1] + eye_r * 0.3 + tear_size,
                fill='lightblue', outline='blue'
            )
            self.canvas.create_oval(
                self.right_eye_center[0] + eye_r * 0.5, self.right_eye_center[1] + eye_r * 0.3,
                self.right_eye_center[0] + eye_r * 0.8, self.right_eye_center[1] + eye_r * 0.3 + tear_size,
                fill='lightblue', outline='blue'
            )
        elif expr == 'winking':
            self.canvas.create_oval(
                self.left_eye_center[0] - eye_r, self.left_eye_center[1] - eye_r,
                self.left_eye_center[0] + eye_r, self.left_eye_center[1] + eye_r,
                fill='black'
            )
            self.canvas.create_line(
                self.right_eye_center[0] - eye_r * 1.5, self.right_eye_center[1],
                self.right_eye_center[0] + eye_r * 1.5, self.right_eye_center[1],
                fill='black', width=3
            )
        elif expr == 'sleeping':
            self.canvas.create_line(
                self.left_eye_center[0] - eye_r * 1.5, self.left_eye_center[1],
                self.left_eye_center[0] + eye_r * 1.5, self.left_eye_center[1],
                fill='black', width=3
            )
            self.canvas.create_line(
                self.right_eye_center[0] - eye_r * 1.5, self.right_eye_center[1],
                self.right_eye_center[0] + eye_r * 1.5, self.right_eye_center[1],
                fill='black', width=3
            )
            z_count = int((self.mouth_animation_frame % 10) / 2)
            for i in range(z_count):
                self.canvas.create_text(
                    self.center_x + self.canvas.winfo_width() * 0.27 + i * 22,
                    self.canvas.winfo_height() * 0.20,
                    text='Z', font=('Arial', 12, 'bold'), fill='blue'
                )
        elif expr == 'laughing':
            self.canvas.create_arc(
                self.left_eye_center[0] - eye_r * 1.3, self.left_eye_center[1] - eye_r * 0.8,
                self.left_eye_center[0] + eye_r * 1.3, self.left_eye_center[1] + eye_r * 0.8,
                start=0, extent=-180, style=tk.ARC, outline='black', width=3
            )
            self.canvas.create_arc(
                self.right_eye_center[0] - eye_r * 1.3, self.right_eye_center[1] - eye_r * 0.8,
                self.right_eye_center[0] + eye_r * 1.3, self.right_eye_center[1] + eye_r * 0.8,
                start=0, extent=-180, style=tk.ARC, outline='black', width=3
            )
            
    def draw_pupils(self):
        eye_r = self.eye_radius
        pupil_r = eye_r * 0.4
        
        offset_x = math.cos(self.eye_angle) * eye_r * 0.3
        offset_y = math.sin(self.eye_angle) * eye_r * 0.3
        
        self.canvas.create_oval(
            self.left_eye_center[0] + offset_x - pupil_r, self.left_eye_center[1] + offset_y - pupil_r,
            self.left_eye_center[0] + offset_x + pupil_r, self.left_eye_center[1] + offset_y + pupil_r,
            fill='black'
        )
        self.canvas.create_oval(
            self.right_eye_center[0] + offset_x - pupil_r, self.right_eye_center[1] + offset_y - pupil_r,
            self.right_eye_center[0] + offset_x + pupil_r, self.right_eye_center[1] + offset_y + pupil_r,
            fill='black'
        )
        
    def draw_mouth(self):
        expr = self.current_expression
        width = max(self.canvas.winfo_width(), 1)
        height = max(self.canvas.winfo_height(), 1)
        scale = min(width, height)

        mouth_width = scale * 0.30
        mouth_height = scale * 0.20
        
        if expr == 'happy':
            arc_extent = -30 - 150 * (self.mouth_animation_frame / 30)
            arc_extent = max(arc_extent, -180)
            self.canvas.create_arc(
                self.center_x - mouth_width, self.mouth_y - mouth_width // 2,
                self.center_x + mouth_width, self.mouth_y + mouth_width,
                start=0, extent=arc_extent, style=tk.ARC, outline='black', width=self.feature_line_width
            )
        elif expr == 'angry':
            self.canvas.create_line(
                self.center_x - mouth_width // 2, self.mouth_y - mouth_width // 3,
                self.center_x + mouth_width // 2, self.mouth_y + mouth_width // 3,
                fill='black', width=self.feature_line_width
            )
        elif expr == 'sad':
            wobble = math.sin(self.mouth_animation_frame * 0.2) * 5
            self.canvas.create_arc(
                self.center_x - mouth_width, self.mouth_y - mouth_width // 3 + wobble,
                self.center_x + mouth_width, self.mouth_y + mouth_width // 2 + wobble,
                start=0, extent=180, style=tk.ARC, outline='black', width=self.feature_line_width
            )
        elif expr == 'joy':
            pulse = math.sin(self.mouth_animation_frame * 0.3) * 5
            self.canvas.create_oval(
                self.center_x - mouth_width // 2 - pulse, self.mouth_y - mouth_width // 3 - pulse,
                self.center_x + mouth_width // 2 + pulse, self.mouth_y + mouth_width // 2 + pulse,
                fill='black'
            )
        elif expr == 'surprise':
            self.canvas.create_oval(
                self.center_x - mouth_width // 3, self.mouth_y - mouth_height // 3,
                self.center_x + mouth_width // 3, self.mouth_y + mouth_height // 2,
                fill='black'
            )
        elif expr == 'fear':
            self.canvas.create_oval(
                self.center_x - mouth_width // 3, self.mouth_y - mouth_height // 4,
                self.center_x + mouth_width // 3, self.mouth_y + mouth_height // 3,
                fill='black'
            )
        elif expr == 'disgust':
            self.canvas.create_line(
                self.center_x - mouth_width // 2, self.mouth_y,
                self.center_x + mouth_width // 2, self.mouth_y + mouth_width // 4,
                fill='black', width=self.feature_line_width
            )
            self.canvas.create_line(
                self.center_x - mouth_width // 3, self.mouth_y + mouth_width // 5,
                self.center_x + mouth_width // 3, self.mouth_y + mouth_width // 3,
                fill='black', width=max(6, self.feature_line_width - 2)
            )
        elif expr == 'neutral':
            self.canvas.create_line(
                self.center_x - mouth_width // 2, self.mouth_y,
                self.center_x + mouth_width // 2, self.mouth_y,
                fill='black', width=self.feature_line_width
            )
        elif expr == 'crying':
            self.canvas.create_arc(
                self.center_x - mouth_width // 2, self.mouth_y - mouth_width // 4,
                self.center_x + mouth_width // 2, self.mouth_y + mouth_width // 3,
                start=0, extent=180, style=tk.ARC, outline='black', width=self.feature_line_width
            )
        elif expr == 'winking':
            self.canvas.create_arc(
                self.center_x - mouth_width // 2, self.mouth_y - mouth_width // 4,
                self.center_x + mouth_width // 2, self.mouth_y + mouth_width // 3,
                start=0, extent=-180, style=tk.ARC, outline='black', width=self.feature_line_width
            )
        elif expr == 'sleeping':
            self.canvas.create_line(
                self.center_x - mouth_width // 3, self.mouth_y,
                self.center_x + mouth_width // 3, self.mouth_y,
                fill='black', width=max(6, self.feature_line_width - 2)
            )
        elif expr == 'laughing':
            laugh_width = mouth_width // 2 + math.sin(self.mouth_animation_frame * 0.2) * 5
            self.canvas.create_arc(
                self.center_x - laugh_width, self.mouth_y - mouth_width // 3,
                self.center_x + laugh_width, self.mouth_y + mouth_width // 2,
                start=0, extent=-180, style=tk.ARC, outline='black', width=self.feature_line_width
            )
            
    def start_eye_animation(self):
        self.eye_angle += 0.15
        if self.eye_angle > math.pi * 2:
            self.eye_angle = 0
            
        self.blink_timer += 1
        if self.blink_timer > 100:
            self.is_blinking = True
            self.blink_timer = 0
            self.window.after(150, self.unblink)
            
        self.draw_face()
        self.window.after(50, self.start_eye_animation)
        
    def unblink(self):
        self.is_blinking = False
        
    def start_mouth_animation(self):
        self.mouth_animation_frame += 1
        self.window.after(100, self.start_mouth_animation)
        
    def update_expression(self):
        # 笑臉提高權重，讓 happy / joy / laughing / winking 更常出現。
        weighted_expressions = [
            'happy', 'happy', 'happy', 'happy',
            'joy', 'joy', 'joy',
            'laughing', 'laughing', 'laughing',
            'winking', 'winking',
            'neutral',
            'surprise',
            'sad',
            'angry',
            'fear',
            'disgust',
            'crying',
            'sleeping'
        ]

        expression = random.choice(weighted_expressions)
        self.current_expression = expression
        self.current_eye_expression = expression

        # 笑臉停留久一點，其他表情較快切換。
        if expression in ('happy', 'joy', 'laughing', 'winking'):
            delay = random.randint(4000, 7000)
        else:
            delay = random.randint(1800, 3500)

        self.window.after(delay, self.update_expression)
        
    def run(self):
        self.window.mainloop()

if __name__ == '__main__':
    face = Face()
    face.run()

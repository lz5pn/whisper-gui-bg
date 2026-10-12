#!/usr/bin/env python3
"""Whisper GUI v4: whisper.cpp transcription and optional offline Argos translation."""
import os
import queue
import shutil
import signal
import subprocess
import tempfile
import time
import re
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

HOME = Path.home()
ROOT = (HOME / 'whisper.cpp') if (HOME / 'whisper.cpp/build/bin/whisper-cli').is_file() else (HOME / '.local/share/whisper-gui/whisper.cpp')
BIN = ROOT / 'build/bin/whisper-cli'
MODELS = ROOT / 'models'
ARGOS_PY = (HOME / 'argos-env/bin/python') if (HOME / 'argos-env/bin/python').is_file() else (HOME / '.local/share/whisper-gui/argos-env/bin/python')
LANGS = {'Автоматично': 'auto', 'Руски': 'ru', 'Английски': 'en', 'Украински': 'uk', 'Български': 'bg', 'Немски': 'de', 'Гръцки': 'el', 'Френски': 'fr', 'Испански': 'es'}
TRANSLATE_LANGS = {'Руски': 'ru', 'Английски': 'en', 'Украински': 'uk', 'Немски': 'de', 'Гръцки': 'el', 'Френски': 'fr', 'Испански': 'es'}


def translate_srt(input_path, output_path, source_code):
    import argostranslate.translate
    languages = argostranslate.translate.get_installed_languages()
    src = next((x for x in languages if x.code == source_code), None)
    bg = next((x for x in languages if x.code == 'bg'), None)
    if not src or not bg:
        raise RuntimeError(f'Липсва езиков пакет {source_code} → bg. Инсталирай го първо.')
    try:
        translator = src.get_translation(bg)
    except Exception as exc:
        raise RuntimeError(f'Няма наличен превод {source_code} → bg. Нужен е езиков пакет.') from exc
    original = Path(input_path).read_text(encoding='utf-8-sig')
    newline = '\r\n' if '\r\n' in original else '\n'
    blocks = re.split(r'\n\s*\n', original.replace('\r\n', '\n').strip())
    result = []
    for block in blocks:
        lines = block.split('\n')
        timing_idx = next((i for i, line in enumerate(lines) if re.match(r'^\s*\d\d:\d\d:\d\d[,\.]\d{3}\s*-->', line)), None)
        if timing_idx is None:
            result.append(block)
            continue
        header = lines[:timing_idx + 1]
        body = '\n'.join(lines[timing_idx + 1:]).strip()
        translated = translator.translate(body) if body else ''
        result.append('\n'.join(header + ([translated] if translated else [])))
    Path(output_path).write_text((newline * 2).join(result) + newline, encoding='utf-8')


class WhisperGUI:
    def __init__(self, root):
        self.root = root
        root.title('Whisper.cpp v4 — субтитри и превод')
        root.geometry('800x625')
        root.minsize(640, 500)
        self.q = queue.Queue()
        self.proc = None
        self.cancelled = False
        self.running = False
        self.started_at = None
        self.progress_value = tk.DoubleVar(value=0)
        self.elapsed = tk.StringVar(value='Изминало време: 00:00')
        self.finished_file = None
        self.source = tk.StringVar()
        self.lang = tk.StringVar(value='Автоматично')
        self.translation_lang = tk.StringVar(value='Руски')
        self.auto_translate = tk.BooleanVar(value=False)
        self.auto_open = tk.BooleanVar(value=False)
        self.model = tk.StringVar(value='small')
        self.status = tk.StringVar(value='Готов за работа')
        self.output = tk.StringVar()
        frame = ttk.Frame(root, padding=15)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Whisper.cpp — субтитри и превод на български', font=('Sans', 14, 'bold')).pack(anchor='w', pady=(0, 12))
        file_row = ttk.Frame(frame)
        file_row.pack(fill='x', pady=4)
        ttk.Entry(file_row, textvariable=self.source).pack(side='left', fill='x', expand=True)
        ttk.Button(file_row, text='Избери видео…', command=self.pick).pack(side='left', padx=(8, 0))
        opts = ttk.Frame(frame)
        opts.pack(fill='x', pady=10)
        ttk.Label(opts, text='Език на речта:').pack(side='left')
        ttk.Combobox(opts, textvariable=self.lang, values=list(LANGS), state='readonly', width=15).pack(side='left', padx=(6, 20))
        ttk.Label(opts, text='Модел:').pack(side='left')
        self.model_combo = ttk.Combobox(opts, textvariable=self.model, state='readonly', width=16)
        self.model_combo.pack(side='left', padx=6)
        self.refresh_models()
        settings = ttk.Frame(frame)
        settings.pack(fill='x', pady=(0, 7))
        ttk.Checkbutton(settings, text='След разпознаването преведи на български', variable=self.auto_translate).pack(anchor='w')
        ttk.Checkbutton(settings, text='Автоматично отвори готовите субтитри в Subtitle Composer', variable=self.auto_open).pack(anchor='w')
        controls = ttk.Frame(frame)
        controls.pack(fill='x', pady=5)
        self.start_btn = ttk.Button(controls, text='▶ Създай субтитри', command=self.start)
        self.start_btn.pack(side='left')
        self.stop_btn = ttk.Button(controls, text='■ Прекрати', command=self.stop, state='disabled')
        self.stop_btn.pack(side='left', padx=8)
        self.open_btn = ttk.Button(controls, text='Отвори субтитрите', command=self.open_subtitles, state='disabled')
        self.open_btn.pack(side='left', padx=8)
        trans = ttk.LabelFrame(frame, text='Локален превод на SRT → български (Argos Translate)', padding=10)
        trans.pack(fill='x', pady=(10, 0))
        ttk.Label(trans, text='Оригинален език:').pack(side='left')
        ttk.Combobox(trans, textvariable=self.translation_lang, values=list(TRANSLATE_LANGS), state='readonly', width=15).pack(side='left', padx=7)
        self.translate_btn = ttk.Button(trans, text='Преведи SRT…', command=self.pick_translation)
        self.translate_btn.pack(side='left', padx=6)
        ttk.Label(frame, textvariable=self.status).pack(anchor='w', pady=(12, 5))
        ttk.Progressbar(frame, mode='determinate', maximum=100, variable=self.progress_value).pack(fill='x')
        progress_row = ttk.Frame(frame)
        progress_row.pack(fill='x', pady=(4, 0))
        ttk.Label(progress_row, textvariable=self.elapsed).pack(side='left')
        self.percent_label = ttk.Label(progress_row, text='0%')
        self.percent_label.pack(side='right')
        ttk.Label(frame, text='Дневник:').pack(anchor='w', pady=(12, 3))
        logframe = ttk.Frame(frame)
        logframe.pack(fill='both', expand=True)
        self.log = tk.Text(logframe, wrap='word', height=10, state='disabled')
        self.log.pack(side='left', fill='both', expand=True)
        scroll = ttk.Scrollbar(logframe, command=self.log.yview)
        scroll.pack(side='right', fill='y')
        self.log.configure(yscrollcommand=scroll.set)
        ttk.Label(frame, textvariable=self.output, foreground='#176b40').pack(anchor='w', pady=(7, 0))
        root.after(100, self.poll)
        root.protocol('WM_DELETE_WINDOW', self.close)

    def refresh_models(self):
        available = sorted(p.name[5:-4] for p in MODELS.glob('ggml-*.bin'))
        self.model_combo['values'] = available
        if available and self.model.get() not in available:
            self.model.set('small' if 'small' in available else available[0])

    def pick(self):
        p = filedialog.askopenfilename(title='Избор на видео или аудио', filetypes=[('Видео и аудио', '*.mp4 *.mkv *.mov *.avi *.webm *.mp3 *.wav *.flac *.ogg *.m4a *.aac'), ('Всички файлове', '*')])
        if p:
            self.source.set(p)
            self.output.set('')

    def append(self, text):
        self.log.configure(state='normal')
        self.log.insert('end', text.rstrip() + '\n')
        self.log.see('end')
        self.log.configure(state='disabled')

    def begin(self, status):
        self.running = True
        self.cancelled = False
        self.start_btn.configure(state='disabled')
        self.translate_btn.configure(state='disabled')
        self.stop_btn.configure(state='normal')
        self.started_at = time.monotonic()
        self.progress_value.set(0)
        self.percent_label.configure(text='0%')
        self.elapsed.set('Изминало време: 00:00')
        self.finished_file = None
        self.open_btn.configure(state='disabled')
        self.output.set('')
        self.status.set(status)

    def start(self):
        if self.running:
            return
        source = Path(self.source.get()).expanduser()
        if not source.is_file():
            messagebox.showerror('Грешка', 'Избери съществуващ видео или аудиофайл.')
            return
        model_path = MODELS / f'ggml-{self.model.get()}.bin'
        if not BIN.is_file() or not model_path.is_file() or not shutil.which('ffmpeg'):
            messagebox.showerror('Липсва компонент', 'Липсва Whisper.cpp, модел или ffmpeg. Стартирай whisper-gui-setup от терминал.')
            return
        spoken = LANGS[self.lang.get()]
        translate = self.auto_translate.get()
        translation_source = spoken if spoken != 'auto' else TRANSLATE_LANGS[self.translation_lang.get()]
        if translate and spoken == 'auto':
            if not messagebox.askokcancel('Език за превод',
                'Whisper ще разпознае езика автоматично, но Argos ще превежда от избрания по-долу език: '
                + self.translation_lang.get() + '.\n\nПровери дали той съвпада с езика на видеото.'):
                return
        if translate and not ARGOS_PY.is_file():
            messagebox.showerror('Argos Translate липсва', 'Argos Translate липсва. Стартирай whisper-gui-setup от терминал.')
            return
        self.begin('Обработване…')
        self.append(f'Файл: {source}')
        threading.Thread(target=self.worker, args=(source, model_path, spoken, translate, translation_source), daemon=True).start()

    def pick_translation(self):
        if self.running:
            return
        if not ARGOS_PY.is_file():
            messagebox.showerror('Argos Translate липсва', 'Argos Translate липсва. Стартирай whisper-gui-setup от терминал.')
            return
        srt = filedialog.askopenfilename(title='Избери SRT за превод', filetypes=[('Субтитри', '*.srt'), ('Всички файлове', '*')], initialdir=str(Path(self.finished_file).parent) if self.finished_file else str(HOME))
        if not srt:
            return
        source = Path(srt)
        target = source.with_name(source.stem + '_BG.srt')
        n = 2
        while target.exists():
            target = source.with_name(f'{source.stem}_BG_{n}.srt')
            n += 1
        self.begin('Превод на български…')
        self.append(f'Превод: {source} → {target}')
        threading.Thread(target=self.translation_worker, args=(source, target, TRANSLATE_LANGS[self.translation_lang.get()]), daemon=True).start()

    def translation_worker(self, source, target, lang):
        try:
            self.run_process([str(ARGOS_PY), str(Path(__file__).resolve()), '--translate-srt', str(source), str(target), lang])
            if not target.is_file():
                raise RuntimeError('Преводът не създаде SRT файл.')
            self.q.put(('done', str(target)))
        except Exception as exc:
            self.q.put(('error', str(exc)))

    def run_process(self, args):
        self.proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace', start_new_session=True, bufsize=1)
        try:
            for line in self.proc.stdout:
                if line.strip():
                    for part in re.split(r'[\r\n]+', line):
                        match = re.search(r'progress\s*=\s*(\d{1,3})\s*%', part, re.IGNORECASE)
                        if match:
                            self.q.put(('progress', min(100, int(match.group(1)))))
                        elif part.strip():
                            self.q.put(('log', part))
            code = self.proc.wait()
            if self.cancelled:
                raise RuntimeError('Обработката е прекратена.')
            if code != 0:
                raise RuntimeError(f'Командата завърши с код {code}. Виж дневника.')
        finally:
            self.proc = None

    def worker(self, source, model_path, language, translate=False, translation_source='ru'):
        target = source.with_suffix('.srt')
        if target.exists():
            target = source.with_name(source.stem + '_whisper.srt')
            n = 2
            while target.exists():
                target = source.with_name(f'{source.stem}_whisper_{n}.srt')
                n += 1
        try:
            with tempfile.TemporaryDirectory(prefix='whispergui-') as tmp:
                wav = Path(tmp) / 'audio.wav'
                self.q.put(('status', 'Извличане на аудио…'))
                self.run_process(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-y', '-i', str(source), '-vn', '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', str(wav)])
                self.q.put(('status', 'Разпознаване на речта…'))
                base = Path(tmp) / 'subtitles'
                self.run_process([str(BIN), '-m', str(model_path), '-f', str(wav), '-l', language, '-t', '4', '--print-progress', '-osrt', '-of', str(base)])
                srt = base.with_suffix('.srt')
                if not srt.is_file():
                    raise RuntimeError('Whisper не създаде SRT файл.')
                shutil.copy2(srt, target)
            final = target
            if translate and not self.cancelled:
                if translation_source == 'bg':
                    self.q.put(('log', 'Речта е на български — превод не е необходим.'))
                else:
                    self.q.put(('status', 'Превод на български…'))
                    bg = target.with_name(target.stem + '_BG.srt')
                    i = 2
                    while bg.exists():
                        bg = target.with_name(f'{target.stem}_BG_{i}.srt')
                        i += 1
                    self.run_process([str(ARGOS_PY), str(Path(__file__).resolve()), '--translate-srt', str(target), str(bg), translation_source])
                    if not bg.is_file():
                        raise RuntimeError('Преводът не създаде SRT файл.')
                    final = bg
            self.q.put(('done', str(final)))
        except Exception as exc:
            self.q.put(('error', str(exc)))

    def stop(self):
        self.cancelled = True
        proc = self.proc
        if proc and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        self.status.set('Прекратяване…')

    def poll(self):
        try:
            while True:
                kind, value = self.q.get_nowait()
                if kind == 'log':
                    self.append(value)
                elif kind == 'status':
                    self.status.set(value)
                elif kind == 'progress':
                    self.progress_value.set(value)
                    self.percent_label.configure(text=f'{value}%')
                elif kind in ('done', 'error'):
                    self.running = False
                    self.started_at = None
                    self.start_btn.configure(state='normal')
                    self.translate_btn.configure(state='normal')
                    self.stop_btn.configure(state='disabled')
                    if kind == 'done':
                        self.status.set('Готово!')
                        self.progress_value.set(100)
                        self.percent_label.configure(text='100%')
                        self.finished_file = value
                        self.open_btn.configure(state='normal')
                        self.output.set('Създаден файл: ' + value)
                        self.append('Успешно: ' + value)
                        if self.auto_open.get():
                            self.open_subtitles()
                    else:
                        self.status.set('Прекратено' if self.cancelled else 'Грешка')
                        self.append('Грешка: ' + value)
                        if not self.cancelled:
                            messagebox.showerror('Грешка', value)
        except queue.Empty:
            pass
        if self.started_at is not None:
            seconds = int(time.monotonic() - self.started_at)
            self.elapsed.set(f'Изминало време: {seconds // 60:02d}:{seconds % 60:02d}')
        self.root.after(100, self.poll)

    def open_subtitles(self):
        if self.finished_file and Path(self.finished_file).is_file():
            program = shutil.which('subtitlecomposer')
            try:
                subprocess.Popen([program, self.finished_file] if program else ['xdg-open', self.finished_file], start_new_session=True)
            except OSError as exc:
                messagebox.showerror('Грешка', str(exc))

    def close(self):
        if self.running:
            if not messagebox.askyesno('Изход', 'Обработката продължава. Да я прекратя ли?'):
                return
            self.stop()
        self.root.destroy()

if __name__ == '__main__':
    if len(sys.argv) == 5 and sys.argv[1] == '--translate-srt':
        try:
            translate_srt(Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4])
        except Exception as exc:
            print(f'Грешка при превод: {exc}', file=sys.stderr)
            sys.exit(1)
    else:
        app = tk.Tk()
        WhisperGUI(app)
        app.mainloop()

import tkinter as tk
from tkinter import scrolledtext, messagebox
import threading
import asyncio
import logging
import subprocess
import os

from main import fetch_matches_for_ui, process_selected_matches

stop_event = None
pipeline_task = None

# Глобальные переменные для хранения состояния чекбоксов
fetched_matches = []
checkbox_vars = []
select_all_var = None  # Переменная для чекбокса "Выбрать все"


class TextHandler(logging.Handler):
    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget

    def emit(self, record):
        msg = self.format(record)

        def append():
            self.text_widget.configure(state='normal')
            self.text_widget.insert(tk.END, msg + '\n')
            self.text_widget.configure(state='disabled')
            self.text_widget.yview(tk.END)

        self.text_widget.after(0, append)


def launch_chrome():
    try:
        chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        if not os.path.exists(chrome_path):
            chrome_path = r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
        if not os.path.exists(chrome_path):
            messagebox.showerror("Ошибка", "Chrome не найден!")
            return
        profile_path = os.path.join(os.getcwd(), "chrome_debug_profile")
        os.makedirs(profile_path, exist_ok=True)
        subprocess.Popen([chrome_path, "--remote-debugging-port=9222", f"--user-data-dir={profile_path}"])
        logging.info("Изолированный Chrome запущен! Авторизуйтесь на нужных сайтах.")
    except Exception as e:
        logging.error(f"Не удалось запустить Chrome: {e}")


# АСИНХРОННЫЕ ОБЕРТКИ

def run_async_fetch(btn_fetch, btn_publish, inner_frame, canvas):
    global fetched_matches, checkbox_vars, select_all_var
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        fetched_matches = loop.run_until_complete(fetch_matches_for_ui())

        def update_ui():
            # Очищаем старые чекбоксы, если они были
            for widget in inner_frame.winfo_children():
                widget.destroy()
            checkbox_vars.clear()

            if not fetched_matches:
                return

            select_all_var.set(True)  # Включаем "Выбрать все" по умолчанию

            # Функция для обновления статуса главного чекбокса
            def update_master(*args):
                all_checked = all(var.get() for var, _ in checkbox_vars)
                select_all_var.set(all_checked)

            # Создаем новые чекбоксы
            for match in fetched_matches:
                var = tk.BooleanVar(value=True)  # По умолчанию галочка стоит

                # Привязываем слежку: если этот чекбокс изменится, проверяем "Выбрать все"
                var.trace_add("write", update_master)

                checkbox_vars.append((var, match))

                # Текст галочки
                cb_text = f"{match.match_date} | {match.team_home} - {match.team_away} (Тур {match.tour_number})"
                cb = tk.Checkbutton(inner_frame, text=cb_text, variable=var, bg="white", font=("Arial", 10))
                cb.pack(anchor="w", padx=5, pady=2)

            inner_frame.update_idletasks()
            canvas.configure(scrollregion=canvas.bbox("all"))
            btn_publish.config(state=tk.NORMAL)
            logging.info("✅ Матчи загружены! Снимите галочки с лишних и нажмите '3. Опубликовать'.")

        btn_fetch.after(0, update_ui)

    except Exception as e:
        logging.error(f"Ошибка при сборе матчей: {e}")
    finally:
        loop.close()
        btn_fetch.after(0, lambda: btn_fetch.config(state=tk.NORMAL, text="2. Собрать расписание"))


async def run_cancellable_publish(selected_matches):
    global pipeline_task
    pipeline_task = asyncio.create_task(process_selected_matches(selected_matches))
    try:
        await pipeline_task
    except asyncio.CancelledError:
        logging.warning("Процесс был принудительно остановлен пользователем!")
    except Exception as e:
        error_msg = str(e).lower()
        if "target closed" in error_msg or "econnrefused" in error_msg:
            logging.error("СВЯЗЬ С БРАУЗЕРОМ ПОТЕРЯНА! Похоже, вы закрыли Chrome.")
        else:
            logging.error(f"Критическая ошибка: {e}")


def run_async_publish(selected_matches, btn_publish, btn_stop):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run_cancellable_publish(selected_matches))
    finally:
        loop.close()
        btn_publish.after(0, lambda: btn_publish.config(state=tk.NORMAL, text="3. Опубликовать выбранные"))
        btn_stop.after(0, lambda: btn_stop.config(state=tk.DISABLED))


# КНОПКИ УПРАВЛЕНИЯ

def toggle_all():
    """Переключает все чекбоксы на основе главного 'Выбрать все'"""
    if not checkbox_vars:
        return
    state = select_all_var.get()
    for var, _ in checkbox_vars:
        var.set(state)


def start_fetch(btn_fetch, btn_publish, inner_frame, canvas):
    btn_fetch.config(state=tk.DISABLED, text="Идет сбор...")
    btn_publish.config(state=tk.DISABLED)
    threading.Thread(target=run_async_fetch, args=(btn_fetch, btn_publish, inner_frame, canvas), daemon=True).start()


def start_publish(btn_publish, btn_stop):
    # Собираем только те матчи, у которых стоит галочка
    selected_matches = [match for var, match in checkbox_vars if var.get()]

    if not selected_matches:
        logging.warning("Вы не выбрали ни одного матча для публикации!")
        return

    btn_publish.config(state=tk.DISABLED, text="Публикуем...")
    btn_stop.config(state=tk.NORMAL)
    threading.Thread(target=run_async_publish, args=(selected_matches, btn_publish, btn_stop), daemon=True).start()


def stop_automation():
    global pipeline_task
    if pipeline_task and not pipeline_task.done():
        logging.info("Посылаем сигнал остановки... Ждем прерывания текущего шага.")
        pipeline_task.get_loop().call_soon_threadsafe(pipeline_task.cancel)


# ИНТЕРФЕЙС

def create_gui():
    global select_all_var

    root = tk.Tk()
    root.title("AFL Publisher")
    root.geometry("900x800")
    root.configure(bg="#f0f0f0")

    try:
        root.iconbitmap("icon.ico")
    except Exception:
        pass

    # Инициализация переменной для "Выбрать все"
    select_all_var = tk.BooleanVar(value=True)

    tk.Label(root, text="Панель управления операторами AFL", font=("Arial", 16, "bold"), bg="#f0f0f0").pack(pady=10)

    tk.Button(root, text="1. Жмыяк (Открыть Chrome с портом 9222)", font=("Arial", 12), bg="#4CAF50", fg="white",
              command=launch_chrome, width=50).pack(pady=5)

    frame_controls = tk.Frame(root, bg="#f0f0f0")
    frame_controls.pack(pady=10)

    btn_fetch = tk.Button(frame_controls, text="2. Собрать расписание", font=("Arial", 12, "bold"), bg="#FF9800",
                          fg="white", width=25)
    btn_fetch.pack(side=tk.LEFT, padx=5)

    btn_publish = tk.Button(frame_controls, text="3. Опубликовать выбранные", font=("Arial", 12, "bold"), bg="#008CBA",
                            fg="white", width=25, state=tk.DISABLED)
    btn_publish.pack(side=tk.LEFT, padx=5)

    btn_stop = tk.Button(frame_controls, text="СТОПЭ", font=("Arial", 12, "bold"), bg="#f44336", fg="white", width=10,
                         state=tk.DISABLED, command=stop_automation)
    btn_stop.pack(side=tk.LEFT, padx=5)

    #  БЛОК С ЗАГОЛОВКОМ И ЧЕКБОКСОМ "ВЫБРАТЬ ВСЕ"
    header_frame = tk.Frame(root, bg="#f0f0f0")
    header_frame.pack(fill=tk.X, padx=20, pady=(10, 0))

    cb_select_all = tk.Checkbutton(header_frame, text="Выбрать все", font=("Arial", 10, "bold"), bg="#f0f0f0",
                                   variable=select_all_var, command=toggle_all)
    cb_select_all.pack(side=tk.LEFT)

    #  БЛОК ДЛЯ ЧЕКБОКСОВ С ПРОКРУТКОЙ И КОЛЕСИКОМ
    list_frame = tk.Frame(root, bg="white", bd=2, relief=tk.SUNKEN)
    list_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(2, 5))

    canvas = tk.Canvas(list_frame, bg="white")
    scrollbar = tk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
    inner_frame = tk.Frame(canvas, bg="white")

    inner_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=inner_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)

    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    # Обработка прокрутки колесика
    def _on_mousewheel(event):
        # Прокручиваем только если контент не помещается в окно
        if canvas.bbox("all")[3] > canvas.winfo_height():
            # event.delta отвечает за направление и силу прокрутки (в Windows обычно кратно 120)
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # Привязываем прокрутку ко всем элементам внутри списка матчей
    canvas.bind_all("<MouseWheel>", _on_mousewheel)

    tk.Label(root, text="Логи (Читаем):", font=("Arial", 10), bg="#f0f0f0").pack(anchor="w", padx=20)
    log_console = scrolledtext.ScrolledText(root, state='disabled', height=12, bg="black", fg="lightgreen",
                                            font=("Consolas", 10))
    log_console.pack(padx=20, pady=5, fill=tk.BOTH, expand=False)

    ui_handler = TextHandler(log_console)
    ui_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%H:%M:%S"))
    logging.getLogger().addHandler(ui_handler)
    logging.getLogger().setLevel(logging.INFO)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    btn_fetch.config(command=lambda: start_fetch(btn_fetch, btn_publish, inner_frame, canvas))
    btn_publish.config(command=lambda: start_publish(btn_publish, btn_stop))

    root.mainloop()


if __name__ == "__main__":
    create_gui()

# -*- coding: utf-8 -*-
"""番茄钟工作学习记录 - 单文件桌面应用 (tkinter + sqlite3)"""
import calendar
import csv
import os
import sqlite3
import sys
import tkinter as tk
from datetime import date
from tkinter import filedialog, messagebox, ttk

# 打包成 exe 后 __file__ 指向临时解压目录，数据库要放在 exe 同级目录
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "pomodoro.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS records(
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               date TEXT NOT NULL,
               project TEXT NOT NULL,
               pomodoros INTEGER NOT NULL DEFAULT 0,
               note TEXT NOT NULL DEFAULT '')"""
    )
    conn.commit()
    return conn


class CalendarDialog(tk.Toplevel):
    """纯 tkinter 日历弹窗，点选日期后回调 selected(YYYY-MM-DD)"""

    def __init__(self, master, initial, on_select):
        super().__init__(master)
        self.title("选择日期")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self.on_select = on_select
        try:
            d = date.fromisoformat(initial)
        except ValueError:
            d = date.today()
        self.year, self.month = d.year, d.month
        self.sel = d
        self.head = ttk.Label(self, text="", font=("", 11, "bold"))
        self.head.grid(row=0, column=1, pady=4)
        ttk.Button(self, text="‹", width=3, command=lambda: self.shift(-1)).grid(row=0, column=0)
        ttk.Button(self, text="›", width=3, command=lambda: self.shift(1)).grid(row=0, column=2)
        self.grid_frame = ttk.Frame(self, padding=6)
        self.grid_frame.grid(row=1, column=0, columnspan=3)
        self._render()
        self.update_idletasks()
        # 居中到主窗口
        x = master.winfo_rootx() + (master.winfo_width() - self.winfo_width()) // 2
        y = master.winfo_rooty() + (master.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

    def shift(self, delta):
        self.month += delta
        if self.month < 1:
            self.month, self.year = 12, self.year - 1
        elif self.month > 12:
            self.month, self.year = 1, self.year + 1
        self._render()

    def _render(self):
        for w in self.grid_frame.winfo_children():
            w.destroy()
        self.head.config(text=f"{self.year} 年 {self.month} 月")
        for c, name in enumerate(["一", "二", "三", "四", "五", "六", "日"]):
            ttk.Label(self.grid_frame, text=name, width=4,
                      anchor="center").grid(row=0, column=c)
        today = date.today()
        for r, week in enumerate(calendar.monthcalendar(self.year, self.month), start=1):
            for c, day in enumerate(week):
                if day == 0:
                    ttk.Label(self.grid_frame, text="", width=4).grid(row=r, column=c)
                    continue
                d = date(self.year, self.month, day)
                btn = tk.Button(self.grid_frame, text=str(day), width=4, relief="flat",
                                command=lambda dd=d: self._pick(dd))
                if d == today:
                    btn.config(bg="#cde4ff")
                if d == self.sel:
                    btn.config(bg="#4a90d9", fg="white")
                btn.grid(row=r, column=c, padx=1, pady=1)

    def _pick(self, d):
        self.on_select(d.isoformat())
        self.destroy()


class RowFrame(ttk.Frame):
    """一条记录行：项目名称 / 番茄个数 / 备注 / 删除按钮"""

    COLS = ("项目名称", "番茄数", "备注")

    def __init__(self, master, on_delete, on_change=None, projects=()):
        super().__init__(master)
        self.project = ttk.Combobox(self, width=22, values=list(projects))
        self.pomodoros = ttk.Spinbox(self, from_=0, to=99, width=6,
                                     command=on_change or (lambda: None))
        self.pomodoros.set(0)
        if on_change:
            self.pomodoros.bind("<KeyRelease>", on_change)
            self.pomodoros.bind("<FocusOut>", on_change)
        self.note = ttk.Entry(self, width=40)
        self.project.grid(row=0, column=0, padx=2, pady=2, sticky="ew")
        self.pomodoros.grid(row=0, column=1, padx=2, pady=2)
        self.note.grid(row=0, column=2, padx=2, pady=2, sticky="ew")
        ttk.Button(self, text="删除", width=5,
                   command=lambda: on_delete(self)).grid(row=0, column=3, padx=2)
        self.columnconfigure(2, weight=1)

    def get(self):
        return (self.project.get().strip(), self.pomodoros.get().strip(),
                self.note.get().strip())

    def set(self, project, pomodoros, note):
        self.project.delete(0, tk.END)
        self.project.insert(0, project)
        self.pomodoros.set(pomodoros)
        self.note.delete(0, tk.END)
        self.note.insert(0, note)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("番茄钟记录")
        self.geometry("780x560")
        self.conn = get_conn()
        self.rows = []
        self.saved_snapshot = []  # 上次加载/提交的内容快照，用于脏检测
        self._build_ui()
        self.load_date()

    def _build_ui(self):
        # ---- 顶部：日期选择 ----
        top = ttk.Frame(self, padding=6)
        top.pack(fill="x")
        ttk.Label(top, text="日期:").pack(side="left")
        ttk.Button(top, text="‹", width=3, command=lambda: self.shift_day(-1)).pack(side="left")
        self.date_var = tk.StringVar(value=date.today().isoformat())
        de = ttk.Entry(top, textvariable=self.date_var, width=12, state="readonly",
                       justify="center")
        de.pack(side="left", padx=2)
        ttk.Button(top, text="›", width=3, command=lambda: self.shift_day(1)).pack(side="left")
        ttk.Button(top, text="📅 选择", command=self.pick_date).pack(side="left", padx=2)
        ttk.Button(top, text="今天", command=self.set_today).pack(side="left", padx=2)
        self.total_var = tk.StringVar(value="当日番茄总数: 0")
        ttk.Label(top, textvariable=self.total_var,
                  font=("", 10, "bold")).pack(side="left", padx=16)
        ttk.Button(top, text="导入CSV", command=self.import_csv).pack(side="right", padx=2)
        ttk.Button(top, text="导出CSV", command=self.export_csv).pack(side="right", padx=2)

        # ---- 表头 ----
        head = ttk.Frame(self, padding=(8, 0))
        head.pack(fill="x")
        ttk.Label(head, text="项目名称", width=26, anchor="w").grid(row=0, column=0, padx=2)
        ttk.Label(head, text="番茄数", width=6, anchor="w").grid(row=0, column=1, padx=2)
        ttk.Label(head, text="备注", anchor="w").grid(row=0, column=2, padx=2)

        # ---- 可滚动行容器 ----
        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True, padx=6)
        canvas = tk.Canvas(wrap, highlightthickness=0)
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        self.rows_area = ttk.Frame(canvas)
        canvas.create_window((0, 0), window=self.rows_area, anchor="nw")
        self.rows_area.bind("<Configure>",
                            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        self.canvas = canvas

        # ---- 底部按钮 ----
        bottom = ttk.Frame(self, padding=6)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="+ 添加行", command=lambda: self.add_row()).pack(side="left")
        ttk.Button(bottom, text="提交保存", command=self.submit).pack(side="right")

    # ---- 行管理 ----
    def get_projects(self):
        cur = self.conn.execute("SELECT DISTINCT project FROM records ORDER BY project")
        return [r[0] for r in cur.fetchall()]

    def refresh_project_values(self):
        projects = self.get_projects()
        for r in self.rows:
            r.project.config(values=projects)

    def add_row(self, project="", pomodoros=0, note=""):
        r = RowFrame(self.rows_area, self.delete_row, self.refresh_total,
                     projects=self.get_projects())
        r.pack(fill="x")
        r.set(project, pomodoros, note)
        self.rows.append(r)
        return r

    def delete_row(self, row):
        self.rows.remove(row)
        row.destroy()

    def clear_rows(self):
        for r in self.rows:
            r.destroy()
        self.rows = []

    # ---- 日期切换（统一走 switch_date，带未保存检测） ----
    def pick_date(self):
        CalendarDialog(self, self.date_var.get(), self.switch_date)

    def set_today(self):
        self.switch_date(date.today().isoformat())

    def shift_day(self, delta):
        d = self.current_date()
        if d is None:
            return
        from datetime import timedelta
        self.switch_date((date.fromisoformat(d) + timedelta(days=delta)).isoformat())

    def switch_date(self, iso):
        if iso == self.date_var.get():
            return
        if not self.maybe_save_changes():
            return  # 用户取消或保存校验失败，停留当前日期
        self.date_var.set(iso)
        self.load_date()

    def current_date(self):
        d = self.date_var.get().strip()
        try:
            date.fromisoformat(d)
        except ValueError:
            messagebox.showerror("错误", "日期格式必须是 YYYY-MM-DD")
            return None
        return d

    # ---- 未保存检测 ----
    def current_entries(self):
        """当前各行规范化后的内容（跳过完全空白行和番茄数为0的行），用于脏检测"""
        entries = []
        for r in self.rows:
            proj, pomo, note = r.get()
            if not proj and not note:
                continue
            try:
                pomo = int(pomo)
            except ValueError:
                pomo = -1  # 非法值视为有改动
            if pomo == 0:
                continue  # 番茄数为0不保存，等同于无内容
            entries.append((proj, pomo, note))
        return entries

    def is_dirty(self):
        return self.current_entries() != self.saved_snapshot

    def maybe_save_changes(self):
        """有未保存改动时询问。返回 True 表示可以继续（已保存/放弃），False 表示取消。"""
        if not self.is_dirty():
            return True
        ans = messagebox.askyesnocancel(
            "未保存的修改", f"{self.date_var.get()} 有未保存的修改。\n是否先保存？\n\n"
                          "是 = 保存并切换    否 = 放弃修改    取消 = 留在当前日期")
        if ans is None:
            return False
        if ans:
            return self.submit(quiet=True)  # 保存成功才允许切换
        return True  # 放弃修改

    def refresh_total(self, *_):
        total = 0
        for r in self.rows:
            try:
                total += int(r.pomodoros.get())
            except (ValueError, tk.TclError):
                pass
        self.total_var.set(f"当日番茄总数: {total}")

    def load_date(self):
        d = self.current_date()
        if d is None:
            return
        self.clear_rows()
        cur = self.conn.execute(
            "SELECT project, pomodoros, note FROM records WHERE date=? ORDER BY id", (d,))
        data = cur.fetchall()
        if not data:
            self.add_row()  # 默认空行
        else:
            for proj, pomo, note in data:
                self.add_row(proj, pomo, note)
        self.saved_snapshot = self.current_entries()
        self.refresh_total()

    # ---- 提交：整日期替换（删除旧记录后重新插入） ----
    def submit(self, quiet=False):
        d = self.current_date()
        if d is None:
            return False
        entries = []
        for r in self.rows:
            proj, pomo, note = r.get()
            if not proj and not note:
                continue
            try:
                pomo = int(pomo)
            except ValueError:
                messagebox.showerror("错误", f"项目“{proj or '(未命名)'}”的番茄数必须是整数")
                return False
            if pomo == 0:
                continue  # 番茄数为0的项目不保存
            if not proj:
                messagebox.showerror("错误", "存在备注但项目名称为空的行")
                return False
            entries.append((d, proj, pomo, note))
        self.conn.execute("DELETE FROM records WHERE date=?", (d,))
        self.conn.executemany(
            "INSERT INTO records(date, project, pomodoros, note) VALUES(?,?,?,?)", entries)
        self.conn.commit()
        self.saved_snapshot = self.current_entries()
        self.refresh_total()
        self.refresh_project_values()  # 新项目名加入下拉
        if not quiet:
            messagebox.showinfo("成功", f"已保存 {d} 的 {len(entries)} 条记录")
        return True

    # ---- CSV 导入/导出 ----
    def export_csv(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", initialfile="pomodoro_export.csv",
            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        cur = self.conn.execute(
            "SELECT date, project, pomodoros, note FROM records ORDER BY date, id")
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["date", "project", "pomodoros", "note"])
            w.writerows(cur.fetchall())
        messagebox.showinfo("成功", f"已导出到 {path}")

    def import_csv(self):
        path = filedialog.askopenfilename(filetypes=[("CSV", "*.csv")])
        if not path:
            return
        try:
            with open(path, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                rows = []
                for i, row in enumerate(reader, start=2):
                    d = (row.get("date") or "").strip()
                    proj = (row.get("project") or "").strip()
                    pomo = (row.get("pomodoros") or "0").strip()
                    note = (row.get("note") or "").strip()
                    date.fromisoformat(d)  # 校验
                    if not proj:
                        raise ValueError(f"第{i}行 project 为空")
                    rows.append((d, proj, int(float(pomo)), note))
        except Exception as e:
            messagebox.showerror("导入失败", str(e))
            return
        self.conn.executemany(
            "INSERT INTO records(date, project, pomodoros, note) VALUES(?,?,?,?)", rows)
        self.conn.commit()
        messagebox.showinfo("成功", f"已导入 {len(rows)} 条记录")
        self.load_date()

    def destroy(self):
        self.conn.close()
        super().destroy()


if __name__ == "__main__":
    App().mainloop()

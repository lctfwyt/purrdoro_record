# -*- coding: utf-8 -*-
"""番茄钟工作学习记录 - 单文件桌面应用 (tkinter + sqlite3)

两个 Tab：
  - 番茄记录：按日期记录项目番茄数
  - 项目管理：项目生命周期（计划中/进行中/已完成/已归档）、tag 分组、笔记(md)
"""
import calendar
import csv
import os
import sqlite3
import sys
import tkinter as tk
from datetime import date
from tkinter import filedialog, messagebox, simpledialog, ttk

# 打包成 exe 后 __file__ 指向临时解压目录，数据要放在 exe 同级目录
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "pomodoro.db")
PROJECTS_DIR = os.path.join(BASE_DIR, "projects")

STATUSES = ("计划中", "进行中", "已完成", "已归档")


def sanitize_filename(name):
    for ch in '\\/:*?"<>|':
        name = name.replace(ch, "_")
    return name.strip() or "untitled"


def note_template(name):
    """带章节头的 md 模板（仅内存中，第一次保存才写入磁盘）"""
    return f"# {name}\n\n## 为什么想做\n\n\n## 学习资料\n\n\n## idea 与规划\n\n"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS records(
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               date TEXT NOT NULL,
               project TEXT NOT NULL DEFAULT '',
               project_id INTEGER,
               pomodoros INTEGER NOT NULL DEFAULT 0,
               note TEXT NOT NULL DEFAULT '')"""
    )
    # ---- 项目 / 标签 ----
    conn.execute(
        """CREATE TABLE IF NOT EXISTS tags(
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               name TEXT UNIQUE NOT NULL)"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS projects(
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               name TEXT UNIQUE NOT NULL,
               status TEXT NOT NULL DEFAULT '进行中',
               created_at TEXT, updated_at TEXT)"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS project_tags(
               project_id INTEGER NOT NULL,
               tag_id INTEGER NOT NULL,
               PRIMARY KEY(project_id, tag_id))"""
    )
    # ---- 迁移：records 加 project_id ----
    cols = [r[1] for r in conn.execute("PRAGMA table_info(records)")]
    if "project_id" not in cols:
        conn.execute("ALTER TABLE records ADD COLUMN project_id INTEGER")
    # ---- 回填：旧记录的项目名 → 自动建项目并关联 ----
    conn.execute(
        """INSERT OR IGNORE INTO projects(name, status, created_at, updated_at)
           SELECT DISTINCT project, '进行中', date('now'), date('now')
           FROM records WHERE project <> ''""")
    conn.execute(
        """UPDATE records SET project_id = (SELECT id FROM projects
           WHERE projects.name = records.project)
           WHERE project_id IS NULL AND project <> ''""")
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


class ProjectTab(ttk.Frame):
    """项目管理 Tab：列表（可点列名排序）+ 详情，支持状态/tag/笔记，无删除"""

    SORTABLE = {
        "name": "p.name",
        "status": "p.status",
        "tags": "tags",
        "pomo": "pomo",
        "first": "first_date",
        "last": "last_date",
    }

    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.conn = app.conn
        self.current_pid = None
        self.sort_key = None   # 当前排序列，None = 默认排序
        self.sort_dir = None   # ASC / DESC
        self.note_baseline = ""  # 加载项目时的笔记内容，用于判断笔记是否被编辑
        self._build_ui()
        self.refresh()

    # ---- UI ----
    def _build_ui(self):
        bar = ttk.Frame(self, padding=6)
        bar.pack(fill="x")
        ttk.Label(bar, text="搜索:").pack(side="left")
        self.search_var = tk.StringVar()
        ttk.Entry(bar, textvariable=self.search_var, width=16).pack(side="left", padx=2)
        self.search_var.trace_add("write", lambda *_: self.refresh())
        ttk.Label(bar, text="状态:").pack(side="left", padx=(10, 0))
        self.status_var = tk.StringVar(value="全部")
        cb = ttk.Combobox(bar, textvariable=self.status_var, values=("全部",) + STATUSES,
                          width=8, state="readonly")
        cb.pack(side="left", padx=2)
        cb.bind("<<ComboboxSelected>>", lambda e: self.refresh())
        ttk.Label(bar, text="标签:").pack(side="left", padx=(10, 0))
        self.tag_var = tk.StringVar(value="全部")
        self.tag_cb = ttk.Combobox(bar, textvariable=self.tag_var, width=10,
                                   state="readonly")
        self.tag_cb.pack(side="left", padx=2)
        self.tag_cb.bind("<<ComboboxSelected>>", lambda e: self.refresh())
        ttk.Button(bar, text="+ 新建项目", command=self.new_project).pack(side="left", padx=(10, 0))
        ttk.Label(bar, text="点击列名排序：降序→升序→原样",
                  foreground="#888").pack(side="right")

        mid = ttk.Frame(self)
        mid.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        left = ttk.Frame(mid)
        left.pack(side="left", fill="both", expand=True)
        self.tree = ttk.Treeview(left,
                                 columns=("name", "status", "tags", "pomo", "first", "last"),
                                 show="headings")
        for c, t, w in (("name", "名称", 150), ("status", "状态", 64),
                        ("tags", "标签", 110), ("pomo", "番茄", 52),
                        ("first", "首次登记", 90), ("last", "最近登记", 90)):
            self.tree.heading(c, text=t, command=lambda col=c: self.on_sort(col))
            self.tree.column(c, width=w, anchor="w")
        vsb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

        right = ttk.Frame(mid, padding=(10, 0, 0, 0))
        right.pack(side="right", fill="y")
        ttk.Label(right, text="项目名称").pack(anchor="w")
        self.name_var = tk.StringVar()
        ttk.Entry(right, textvariable=self.name_var, width=30).pack(fill="x")
        ttk.Label(right, text="状态").pack(anchor="w", pady=(6, 0))
        self.status_edit_var = tk.StringVar()
        ttk.Combobox(right, textvariable=self.status_edit_var, values=STATUSES,
                     width=28, state="readonly").pack(fill="x")
        ttk.Label(right, text="标签（手动输入，逗号分隔；可下拉选已有）").pack(anchor="w", pady=(6, 0))
        self.tags_var = tk.StringVar()
        self.tags_entry = ttk.Combobox(right, textvariable=self.tags_var,
                                        values=self._all_tags(), width=28)
        self.tags_entry.pack(fill="x")
        ttk.Label(right, text="笔记（保存后写入 projects/{id}_{名称}.md）").pack(anchor="w", pady=(6, 0))
        btns = ttk.Frame(right)
        btns.pack(side="bottom", fill="x", pady=(6, 0))
        ttk.Button(btns, text="保存", command=self.save_project).pack(side="left")
        ttk.Button(btns, text="归档", command=self.archive_project).pack(side="left", padx=4)
        ttk.Button(btns, text="打开目录", command=self.open_dir).pack(side="right")
        nwrap = ttk.Frame(right)
        nwrap.pack(fill="both", expand=True)
        self.note = tk.Text(nwrap, width=46, height=9, wrap="word")
        nvsb = ttk.Scrollbar(nwrap, orient="vertical", command=self.note.yview)
        self.note.configure(yscrollcommand=nvsb.set)
        self.note.pack(side="left", fill="both", expand=True)
        nvsb.pack(side="right", fill="y")

    # ---- 列表 ----
    def _all_tags(self):
        return [r[0] for r in self.conn.execute("SELECT name FROM tags ORDER BY name")]

    def refresh(self):
        all_tags = self._all_tags()
        cur_tag = self.tag_var.get()
        self.tag_cb.config(values=["全部"] + all_tags)
        self.tags_entry.config(values=all_tags)
        if cur_tag not in ["全部"] + all_tags:
            self.tag_var.set("全部")
        for i in self.tree.get_children():
            self.tree.delete(i)
        sql = """SELECT p.id, p.name, p.status,
                        (SELECT GROUP_CONCAT(t.name, ', ') FROM project_tags pt
                         JOIN tags t ON t.id = pt.tag_id WHERE pt.project_id = p.id) AS tags,
                        (SELECT COALESCE(SUM(r.pomodoros),0) FROM records r
                         WHERE r.project_id = p.id) AS pomo,
                        (SELECT MIN(r.date) FROM records r WHERE r.project_id = p.id) AS first_date,
                        (SELECT MAX(r.date) FROM records r WHERE r.project_id = p.id) AS last_date
                 FROM projects p WHERE 1=1"""
        params = []
        kw = self.search_var.get().strip()
        if kw:
            sql += " AND p.name LIKE ?"
            params.append(f"%{kw}%")
        st = self.status_var.get()
        if st != "全部":
            sql += " AND p.status = ?"
            params.append(st)
        tg = self.tag_var.get()
        if tg != "全部":
            sql += (" AND p.id IN (SELECT pt.project_id FROM project_tags pt"
                    " JOIN tags t ON t.id = pt.tag_id WHERE t.name = ?)")
            params.append(tg)
        if self.sort_key in self.SORTABLE:
            sql += f" ORDER BY {self.SORTABLE[self.sort_key]} {self.sort_dir}, p.id"
        else:
            sql += " ORDER BY p.updated_at DESC, p.id DESC"
        for pid, name, status, tags, pomo, first, last in self.conn.execute(sql, params):
            self.tree.insert("", "end", iid=str(pid),
                             values=(name, status, tags or "", pomo,
                                     (first or "")[:10], (last or "")[:10]))

    def on_sort(self, col):
        """点击列名：循环 降序 → 升序 → 恢复原样"""
        if self.sort_key != col:
            self.sort_key, self.sort_dir = col, "DESC"
        elif self.sort_dir == "DESC":
            self.sort_dir = "ASC"
        else:
            self.sort_key, self.sort_dir = None, None
        self.refresh()

    # ---- 笔记文件（懒创建，命名 {id}_{名称}.md） ----
    def note_path(self, pid, name):
        return os.path.join(PROJECTS_DIR, f"{pid}_{sanitize_filename(name)}.md")

    def find_note_file(self, pid, name):
        """优先新命名，其次兼容旧版 {id}.md / 改名前的 {id}_{旧名}.md"""
        newp = self.note_path(pid, name)
        if os.path.exists(newp):
            return newp
        if not os.path.isdir(PROJECTS_DIR):
            return None
        for fn in os.listdir(PROJECTS_DIR):
            if fn == f"{pid}.md" or (fn.startswith(f"{pid}_") and fn.endswith(".md")):
                return os.path.join(PROJECTS_DIR, fn)
        return None

    def save_note(self, pid, name, content, changed, old_name=None):
        existing = self.find_note_file(pid, name)
        target = self.note_path(pid, name)
        os.makedirs(PROJECTS_DIR, exist_ok=True)
        if not changed:
            # 笔记未编辑：不创建/修改文件；仅当项目改名且已有文件时重命名（含旧版 {id}.md 迁移）
            if existing and os.path.abspath(existing) != os.path.abspath(target):
                self._rename_note_file(existing, target, old_name or name, name)
            return
        if content.strip():
            if existing and os.path.abspath(existing) != os.path.abspath(target):
                try:
                    os.remove(existing)
                except OSError:
                    pass
            with open(target, "w", encoding="utf-8") as f:
                f.write(content)
        elif existing:
            try:
                os.remove(existing)  # 内容清空则删除文件，保持目录干净
            except OSError:
                pass

    def _rename_note_file(self, existing, target, old_name, new_name):
        try:
            if old_name != new_name:
                with open(existing, encoding="utf-8") as f:
                    lines = f.readlines()
                if lines and lines[0].strip() == f"# {old_name}":
                    lines[0] = f"# {new_name}\n"
                    with open(existing, "w", encoding="utf-8") as f:
                        f.writelines(lines)
            os.replace(existing, target)
        except OSError:
            pass

    def on_select(self, _event=None):
        sel = self.tree.selection()
        if sel:
            self.load_project(int(sel[0]))

    def load_project(self, pid):
        row = self.conn.execute("SELECT name, status FROM projects WHERE id=?", (pid,)).fetchone()
        if not row:
            return
        name, status = row
        self.current_pid = pid
        self.name_var.set(name)
        self.status_edit_var.set(status)
        tags = [r[0] for r in self.conn.execute(
            "SELECT t.name FROM tags t JOIN project_tags pt ON t.id=pt.tag_id"
            " WHERE pt.project_id=? ORDER BY t.name", (pid,))]
        self.tags_var.set(", ".join(tags))
        self.note.delete("1.0", tk.END)
        f = self.find_note_file(pid, name)
        if f:
            with open(f, encoding="utf-8") as fh:
                self.note.insert("1.0", fh.read())
        else:
            self.note.insert("1.0", note_template(name))
        self.note_baseline = self.note.get("1.0", "end-1c")

    # ---- 新建 / 保存 / 归档 ----
    def new_project(self):
        name = simpledialog.askstring("新建项目", "项目名称：", parent=self)
        if not name:
            return
        name = name.strip()
        if not name:
            return
        if self.conn.execute("SELECT 1 FROM projects WHERE name=?", (name,)).fetchone():
            messagebox.showerror("错误", f"项目名「{name}」已存在")
            return
        now = date.today().isoformat()
        cur = self.conn.execute(
            "INSERT INTO projects(name, status, created_at, updated_at) VALUES(?,?,?,?)",
            (name, "计划中", now, now))
        pid = cur.lastrowid
        self.conn.commit()
        self.refresh()
        self.tree.selection_set(str(pid))
        self.tree.see(str(pid))
        self.load_project(pid)
        self.app.refresh_project_values()

    def save_project(self):
        if self.current_pid is None:
            return
        pid = self.current_pid
        name = self.name_var.get().strip()
        if not name:
            messagebox.showerror("错误", "项目名称不能为空")
            return
        if self.conn.execute("SELECT 1 FROM projects WHERE name=? AND id<>?",
                             (name, pid)).fetchone():
            messagebox.showerror("错误", f"项目名「{name}」已存在")
            return
        old_name = self.conn.execute("SELECT name FROM projects WHERE id=?", (pid,)).fetchone()[0]
        status = self.status_edit_var.get() or "进行中"
        now = date.today().isoformat()
        self.conn.execute("UPDATE projects SET name=?, status=?, updated_at=? WHERE id=?",
                          (name, status, now, pid))
        if name != old_name:
            self.conn.execute("UPDATE records SET project=? WHERE project_id=?", (name, pid))
        # tags：整组替换（合并/拆分 = 增删 tag 关联，完全可逆）
        self.conn.execute("DELETE FROM project_tags WHERE project_id=?", (pid,))
        for t in [x.strip() for x in self.tags_var.get().split(",") if x.strip()]:
            self.conn.execute("INSERT OR IGNORE INTO tags(name) VALUES(?)", (t,))
            tid = self.conn.execute("SELECT id FROM tags WHERE name=?", (t,)).fetchone()[0]
            self.conn.execute("INSERT OR IGNORE INTO project_tags(project_id, tag_id) VALUES(?,?)",
                              (pid, tid))
        # 笔记：只有编辑过才写/删文件；仅改名时把已有文件重命名
        note = self.note.get("1.0", "end-1c")
        self.save_note(pid, name, note, note != self.note_baseline, old_name)
        self.note_baseline = note
        self.conn.commit()
        self.refresh()
        self.app.refresh_project_values()
        messagebox.showinfo("成功", "已保存")

    def archive_project(self):
        if self.current_pid is None:
            return
        self.status_edit_var.set("已归档")
        self.save_project()

    def open_dir(self):
        os.makedirs(PROJECTS_DIR, exist_ok=True)
        try:
            os.startfile(PROJECTS_DIR)
        except OSError:
            messagebox.showerror("错误", "无法打开目录")


class HistoryTab(ttk.Frame):
    """历史番茄 Tab：按项目回看历史记录，逐条编辑（项目/日期/数量/备注），无删除"""

    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.conn = app.conn
        self.current_rid = None  # 当前选中记录 id
        self._build_ui()
        self.refresh()

    # ---- UI ----
    def _build_ui(self):
        bar = ttk.Frame(self, padding=6)
        bar.pack(fill="x")
        ttk.Label(bar, text="项目:").pack(side="left")
        self.project_var = tk.StringVar()
        self.proj_cb = ttk.Combobox(bar, textvariable=self.project_var,
                                    width=20, state="readonly")
        self.proj_cb.pack(side="left", padx=2)
        self.proj_cb.bind("<<ComboboxSelected>>", lambda e: self.refresh())
        ttk.Label(bar, text="点击行可编辑下方记录详情", foreground="#888").pack(side="right")

        mid = ttk.Frame(self)
        mid.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        left = ttk.Frame(mid)
        left.pack(side="left", fill="both", expand=True)
        self.tree = ttk.Treeview(left, columns=("date", "project", "pomodoros", "note"),
                                 show="headings")
        for c, t, w in (("date", "日期", 100), ("project", "项目", 140),
                        ("pomodoros", "番茄数", 60), ("note", "备注", 200)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w")
        vsb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self.on_select_record)

        right = ttk.Frame(mid, padding=(10, 0, 0, 0))
        right.pack(side="right", fill="y")
        ttk.Label(right, text="日期").pack(anchor="w")
        dfrm = ttk.Frame(right)
        dfrm.pack(fill="x")
        self.date_edit_var = tk.StringVar()
        ttk.Entry(dfrm, textvariable=self.date_edit_var, width=24).pack(side="left")
        ttk.Button(dfrm, text="📅 选择", width=8,
                   command=lambda: CalendarDialog(
                       self, self.date_edit_var.get() or date.today().isoformat(),
                       self.date_edit_var.set)).pack(side="left", padx=2)
        ttk.Label(right, text="项目").pack(anchor="w", pady=(6, 0))
        self.proj_edit_var = tk.StringVar()
        self.proj_edit_cb = ttk.Combobox(right, textvariable=self.proj_edit_var, width=30)
        self.proj_edit_cb.pack(fill="x")
        ttk.Label(right, text="番茄数").pack(anchor="w", pady=(6, 0))
        self.pomo = ttk.Spinbox(right, from_=0, to=999, width=8)
        self.pomo.set(0)
        self.pomo.pack(fill="x")
        ttk.Label(right, text="备注").pack(anchor="w", pady=(6, 0))
        self.note_edit_var = tk.StringVar()
        ttk.Entry(right, textvariable=self.note_edit_var, width=30).pack(fill="x")
        btns = ttk.Frame(right)
        btns.pack(side="bottom", fill="x", pady=(6, 0))
        ttk.Button(btns, text="保存", command=self.save_record).pack(side="left")

    # ---- 列表 ----
    def all_projects(self):
        return [r[0] for r in self.conn.execute(
            "SELECT name FROM projects ORDER BY updated_at DESC, id DESC")]

    def refresh(self):
        projs = self.all_projects()
        self.proj_cb.config(values=projs)
        self.proj_edit_cb.config(values=projs)
        cur = self.project_var.get()
        if cur not in projs:
            self.project_var.set(projs[0] if projs else "")
        for i in self.tree.get_children():
            self.tree.delete(i)
        name = self.project_var.get()
        if name:
            for rid, dt, proj, pomo, note in self.conn.execute(
                    "SELECT id, date, project, pomodoros, note FROM records"
                    " WHERE project_id=(SELECT id FROM projects WHERE name=?)"
                    " ORDER BY date DESC, id DESC", (name,)):
                self.tree.insert("", "end", iid=str(rid),
                                 values=(dt, proj, pomo, note))
        self._clear_detail()

    def _clear_detail(self):
        self.current_rid = None
        self.date_edit_var.set("")
        self.proj_edit_var.set("")
        self.pomo.set(0)
        self.note_edit_var.set("")

    def on_select_record(self, _event=None):
        sel = self.tree.selection()
        if not sel:
            return
        self.current_rid = int(sel[0])
        row = self.conn.execute(
            "SELECT date, project, pomodoros, note FROM records WHERE id=?",
            (self.current_rid,)).fetchone()
        if not row:
            self._clear_detail()
            return
        self.date_edit_var.set(row[0])
        self.proj_edit_var.set(row[1])
        self.pomo.set(row[2])
        self.note_edit_var.set(row[3])

    # ---- 保存（无删除） ----
    def save_record(self):
        if self.current_rid is None:
            messagebox.showerror("错误", "请先在左侧选择一条记录")
            return
        new_name = self.proj_edit_var.get().strip()
        if not new_name:
            messagebox.showerror("错误", "项目名称不能为空")
            return
        d = self.date_edit_var.get().strip()
        try:
            date.fromisoformat(d)
        except ValueError:
            messagebox.showerror("错误", "日期格式必须是 YYYY-MM-DD")
            return
        try:
            pomo = int(self.pomo.get())
        except ValueError:
            messagebox.showerror("错误", "番茄数必须是整数")
            return
        if pomo < 0:
            messagebox.showerror("错误", "番茄数不能为负数")
            return
        note = self.note_edit_var.get().strip()
        pid = self.app.resolve_project_id(new_name)  # 改名/新建项目都同步 project_id 与名称快照
        self.conn.execute(
            "UPDATE records SET date=?, project_id=?, project=?, pomodoros=?, note=? WHERE id=?",
            (d, pid, new_name, pomo, note, self.current_rid))
        self.conn.commit()
        self.refresh()
        self.app.project_tab.refresh()
        self.app.refresh_project_values()
        messagebox.showinfo("成功", "已保存")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("番茄钟记录")
        self.geometry("1000x400")
        self.conn = get_conn()
        self.rows = []
        self.saved_snapshot = []  # 上次加载/提交的内容快照，用于脏检测
        self._build_ui()
        self.load_date()

    def _build_ui(self):
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)

        # ============ Tab1 番茄记录 ============
        tab1 = ttk.Frame(self.nb)
        self.nb.add(tab1, text="番茄记录")

        # 顶部：日期选择
        top = ttk.Frame(tab1, padding=6)
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

        # 表头
        head = ttk.Frame(tab1, padding=(8, 0))
        head.pack(fill="x")
        ttk.Label(head, text="项目名称", width=26, anchor="w").grid(row=0, column=0, padx=2)
        ttk.Label(head, text="番茄数", width=6, anchor="w").grid(row=0, column=1, padx=2)
        ttk.Label(head, text="备注", anchor="w").grid(row=0, column=2, padx=2)

        # 可滚动行容器
        wrap = ttk.Frame(tab1)
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

        # 底部按钮
        bottom = ttk.Frame(tab1, padding=6)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="+ 添加行", command=lambda: self.add_row()).pack(side="left")
        ttk.Button(bottom, text="提交保存", command=self.submit).pack(side="right")

        # ============ Tab2 项目管理 ============
        tab2 = ttk.Frame(self.nb)
        self.nb.add(tab2, text="项目管理")
        self.project_tab = ProjectTab(tab2, self)
        self.project_tab.pack(fill="both", expand=True)

        # ============ Tab3 历史番茄 ============
        tab3 = ttk.Frame(self.nb)
        self.nb.add(tab3, text="历史番茄")
        self.history_tab = HistoryTab(tab3, self)
        self.history_tab.pack(fill="both", expand=True)
        self.nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        # 窗口真正渲染后再按所需高度调整，保证项目管理 tab 底部按钮完全可见
        self.after(80, self._fit_window_height)

    def _fit_window_height(self):
        self.update_idletasks()
        self.geometry(f"1000x{max(400, self.nb.winfo_reqheight() + 45)}")

    def _on_tab_changed(self, _event=None):
        # 切到历史番茄时刷新，保证看到最新数据（每日提交/项目改名后）
        if self.nb.index(self.nb.select()) == 2:
            self.history_tab.refresh()

    # ---- 行管理 ----
    def get_projects(self):
        """番茄下拉只显示进行中的项目"""
        cur = self.conn.execute(
            "SELECT name FROM projects WHERE status='进行中' ORDER BY name")
        return [r[0] for r in cur.fetchall()]

    def refresh_project_values(self):
        projects = self.get_projects()
        for r in self.rows:
            r.project.config(values=projects)

    def resolve_project_id(self, name):
        """按名称找项目，找不到则自动新建为「进行中」项目（笔记懒创建，不落盘）"""
        row = self.conn.execute("SELECT id FROM projects WHERE name=?", (name,)).fetchone()
        if row:
            return row[0]
        now = date.today().isoformat()
        cur = self.conn.execute(
            "INSERT INTO projects(name, status, created_at, updated_at) VALUES(?,?,?,?)",
            (name, "进行中", now, now))
        return cur.lastrowid

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
        rows = []
        for d2, proj, pomo, note in entries:
            pid = self.resolve_project_id(proj)
            rows.append((d2, pid, proj, pomo, note))
        self.conn.execute("DELETE FROM records WHERE date=?", (d,))
        self.conn.executemany(
            "INSERT INTO records(date, project_id, project, pomodoros, note) VALUES(?,?,?,?,?)",
            rows)
        self.conn.commit()
        self.saved_snapshot = self.current_entries()
        self.refresh_total()
        self.refresh_project_values()  # 新项目名加入下拉
        self.project_tab.refresh()     # 累计番茄/列表刷新
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
                    pid = self.resolve_project_id(proj)
                    rows.append((d, pid, proj, int(float(pomo)), note))
        except Exception as e:
            messagebox.showerror("导入失败", str(e))
            return
        self.conn.executemany(
            "INSERT INTO records(date, project_id, project, pomodoros, note) VALUES(?,?,?,?,?)",
            rows)
        self.conn.commit()
        messagebox.showinfo("成功", f"已导入 {len(rows)} 条记录")
        self.load_date()
        self.project_tab.refresh()

    def destroy(self):
        self.conn.close()
        super().destroy()


if __name__ == "__main__":
    App().mainloop()

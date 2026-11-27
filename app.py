import os, sys, sqlite3, threading, shutil, re, uuid
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageGrab, ImageOps
import fitz
import pytesseract
from household import parse_rows, matches

BASE = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "AswesumaSmartOCR"
BASE.mkdir(parents=True, exist_ok=True)
PAGES = BASE / "pages"
PAGES.mkdir(exist_ok=True)
DB = BASE / "index.sqlite"
bundle = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "ocr"
if (bundle / "tesseract.exe").exists():
    pytesseract.pytesseract.tesseract_cmd = str(bundle / "tesseract.exe")
    os.environ["TESSDATA_PREFIX"] = str(bundle / "tessdata")
def connect():
    c = sqlite3.connect(DB)
    c.execute("CREATE TABLE IF NOT EXISTS pages(id INTEGER PRIMARY KEY, source TEXT, page INTEGER, image TEXT, body TEXT, UNIQUE(image))")
    return c
def normalize(s):
    return re.sub(r"[^\w]", "", s.casefold())
root = tk.Tk()
root.title("ASWESUMA SMART OCR - V1.0.1 Preview")
root.geometry("1050x650")
root.configure(bg="#f4f5f7")
ttk.Style().theme_use("clam")
ttk.Label(root,text="ASWESUMA SMART OCR",font=("Segoe UI",24,"bold")).pack(pady=15)
bar=ttk.Frame(root); bar.pack(fill="x",padx=18)
status=tk.StringVar(value="Ready • Local storage only")
query=tk.StringVar()
mode=tk.StringVar(value='All')
lang=tk.StringVar(value="eng+tam+sin")
busy=False
def notify(s):
    root.after(0,lambda:status.set(s))
def index_files(paths):
    global busy
    if busy or not paths: return
    busy=True
    selected=lang.get()
    def worker():
        global busy
        count=0
        try:
            with connect() as c:
                for path in paths:
                    if Path(path).suffix.lower()==".pdf":
                        with fitz.open(path) as doc:
                            for i,p in enumerate(doc):
                                pix=p.get_pixmap(dpi=300,alpha=False)
                                im=Image.frombytes("RGB",(pix.width,pix.height),pix.samples)
                                save_page(c,im,path,i+1,selected,p.get_text())
                                count+=1
                    else:
                        with Image.open(path) as im:
                            save_page(c,im.convert("RGB"),path,1,selected,"")
                            count+=1
                    notify(f"Indexed {count} pages")
            root.after(0,search)
        except Exception as e:
            notify("Error: "+str(e))
        finally: busy=False
    threading.Thread(target=worker,daemon=True).start()
def save_page(c,im,source,page,language,existing):
    import hashlib
    key=hashlib.sha256(im.tobytes()+str(im.size).encode()).hexdigest()
    dest=PAGES/(key+".png")
    if c.execute("SELECT 1 FROM pages WHERE image=?",(str(dest),)).fetchone(): return
    body=existing if existing.strip() else pytesseract.image_to_string(ImageOps.autocontrast(ImageOps.grayscale(im)),lang=language)
    im.save(dest)
    c.execute("INSERT INTO pages(source,page,image,body) VALUES(?,?,?,?)",(Path(source).name,page,str(dest),body))
    c.commit()
def choose():
    index_files(filedialog.askopenfilenames(filetypes=[("Documents","*.pdf *.png *.jpg *.jpeg *.bmp *.webp")]))
def capture():
    root.withdraw()
    def take():
        try:
            path=BASE/("capture-"+uuid.uuid4().hex+".png")
            ImageGrab.grab().save(path)
            index_files([str(path)])
        except Exception as e: status.set(str(e))
        finally: root.deiconify()
    root.after(700,take)
def search(*args):
    q=query.get().strip()
    tree.delete(*tree.get_children())
    total=0
    with connect() as c:
        for id,body in c.execute("SELECT id,body FROM pages"):
            for n,row in enumerate(parse_rows(body)):
                if matches(row,q,mode.get()):
                    order,hh,name,address=row
                    tree.insert("","end",iid=f"{id}:{n}",values=(order,name,address))
                    total+=1
    status.set(f"{total} matching household rows • Verify against original")
def original():
    if not tree.selection(): return
    with connect() as c:
        row=c.execute("SELECT image FROM pages WHERE id=?",(tree.selection()[0].split(':')[0],)).fetchone()
    if row: os.startfile(row[0])
def export_pdf():
    path=filedialog.asksaveasfilename(defaultextension=".pdf",filetypes=[("PDF","*.pdf")])
    if not path:return
    with connect() as c: rows=c.execute("SELECT image FROM pages ORDER BY id").fetchall()
    if not rows:return
    with fitz.open() as doc:
        for (img,) in rows:
            with fitz.open(img) as image: doc.insert_pdf(fitz.open("pdf",image.convert_to_pdf()))
        doc.save(path)
    status.set("Image PDF saved")
for label,cmd in [("Capture screen",capture),("Import images / PDF",choose),("Save all as PDF",export_pdf),("View original",original)]:
    ttk.Button(bar,text=label,command=cmd).pack(side="left",padx=5)
ttk.Combobox(bar,textvariable=lang,values=["eng+tam+sin","eng","tam","sin"],state="readonly",width=15).pack(side="right")
ttk.Label(root,text="Search by HH Number / Name / House Number / Address").pack(pady=(20,3))
entry=ttk.Entry(root,textvariable=query,font=("Segoe UI",15));entry.pack(fill="x",padx=22)
selector=ttk.Combobox(root,textvariable=mode,values=["All","HH Number","Name","House Number","Address"],state="readonly")
selector.pack(pady=5)
selector.bind("<<ComboboxSelected>>",search)
query.trace_add("write",search)
tree=ttk.Treeview(root,columns=("order","name","address"),show="headings")
for col,w in [("order",100),("name",360),("address",540)]:
    tree.heading(col,text="Order No." if col=="order" else col.title());tree.column(col,width=w)
tree.pack(fill="both",expand=True,padx=22,pady=10)
tree.bind("<Double-1>",lambda e:original())
ttk.Label(root,textvariable=status).pack()
ttk.Label(root,text="Developed by Razmi Mohamed • Verify OCR against original • Preview").pack(pady=8)
search()
root.mainloop()

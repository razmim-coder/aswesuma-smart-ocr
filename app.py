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
DOCS = BASE / 'documents'
DOCS.mkdir(exist_ok=True)
DB = BASE / "index.sqlite"
bundle = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "ocr"
if (bundle / "tesseract.exe").exists():
    pytesseract.pytesseract.tesseract_cmd = str(bundle / "tesseract.exe")
    os.environ["TESSDATA_PREFIX"] = str(bundle / "tessdata")
def connect():
    c = sqlite3.connect(DB)
    c.execute("CREATE TABLE IF NOT EXISTS pages(id INTEGER PRIMARY KEY, source TEXT, page INTEGER, image TEXT, body TEXT, UNIQUE(image))")
    c.execute("CREATE TABLE IF NOT EXISTS documents(path TEXT PRIMARY KEY, name TEXT, state TEXT)")
    return c
def normalize(s):
    return re.sub(r"[^\w]", "", s.casefold())
root = tk.Tk()
root.title("ASWESUMA SMART OCR - V1.0.3 Preview")
root.geometry("1050x650")
root.configure(bg="#f4f5f7")
ttk.Style().theme_use("clam")
ttk.Label(root,text="ASWESUMA SMART OCR",font=("Segoe UI",24,"bold")).pack(pady=15)
bar=ttk.Frame(root); bar.pack(fill="x",padx=18)
status=tk.StringVar(value="Ready • Local storage only")
query=tk.StringVar()
mode=tk.StringVar(value='All')
summary=tk.StringVar()
lang=tk.StringVar(value="eng+tam+sin")
busy=False
def notify(s):
    root.after(0,lambda:status.set(s))
def index_files(paths, reuse=False):
    global busy
    if busy:
        messagebox.showinfo("Import","Another import is running.")
        return
    if not paths: return
    busy=True
    selected=lang.get()
    status.set("Importing documents...")
    def worker():
        global busy
        count=0
        errors=[]
        try:
            with connect() as c:
                for path in paths:
                    saved=Path(path) if reuse else DOCS/(uuid.uuid4().hex+"_"+Path(path).name)
                    try:
                        if not reuse:
                            shutil.copy2(path,saved)
                            c.execute("INSERT INTO documents VALUES(?,?,?)",(str(saved),Path(path).name,"Saved; OCR pending"))
                        c.commit()
                        notify(f"Saved {Path(path).name}; processing OCR")
                        if saved.suffix.lower()==".pdf":
                            with fitz.open(saved) as doc:
                                if doc.needs_pass: raise ValueError("Password-protected PDF")
                                for i,p in enumerate(doc):
                                    pix=p.get_pixmap(dpi=300,alpha=False)
                                    im=Image.frombytes("RGB",(pix.width,pix.height),pix.samples)
                                    save_page(c,im,path,i+1,selected,p.get_text(sort=True),p)
                                    count+=1
                                    notify(f"Processing page {i+1}/{len(doc)}")
                        else:
                            with Image.open(saved) as im:
                                save_page(c,im.convert("RGB"),path,1,selected,"")
                                count+=1
                        c.execute("UPDATE documents SET state=? WHERE path=?",("Indexed",str(saved)))
                        c.commit()
                    except Exception as e:
                        errors.append(Path(path).name+": "+str(e))
                        c.execute("UPDATE documents SET state=? WHERE path=?",("OCR/import error: "+str(e),str(saved)))
                        c.commit()
            def finish():
                search()
                status.set(f"Processed {count} pages; {len(errors)} document errors. See Saved Documents.")
                if errors: messagebox.showwarning("Import errors","\n".join(errors))
                else: messagebox.showinfo("Import complete",f"Processed {count} pages. Originals saved in Saved Documents.")
            root.after(0,finish)
        except Exception as e:
            notify("Error: "+str(e))
        finally: busy=False
    threading.Thread(target=worker,daemon=True).start()
def save_page(c,im,source,page,language,existing,pdf_page=None):
    import hashlib
    key=hashlib.sha256(im.tobytes()+str(im.size).encode()).hexdigest()
    dest=PAGES/(key+".png")
    im.save(dest)
    body=existing
    if pdf_page is not None:
        try:
            table_rows=[]
            for table in pdf_page.find_tables().tables:
                for cells in table.extract():
                    table_rows.append(" | ".join(" ".join((v or "").split()) for v in cells))
            candidate="\n".join(table_rows)
            if list(parse_rows(candidate)): body=candidate
        except Exception:
            pass
    if not list(parse_rows(body)):
        try:
            candidate=pytesseract.image_to_string(ImageOps.autocontrast(ImageOps.grayscale(im)),lang=language,config="--psm 6 -c preserve_interword_spaces=1")
            if list(parse_rows(candidate)) or not body.strip(): body=candidate
        except Exception:
            if not body.strip(): raise
    c.execute("INSERT INTO pages(source,page,image,body) VALUES(?,?,?,?) ON CONFLICT(image) DO UPDATE SET body=CASE WHEN length(excluded.body)>0 THEN excluded.body ELSE pages.body END",(Path(source).name,page,str(dest),body))
    c.commit()
def choose_pdf():
    index_files(filedialog.askopenfilenames(filetypes=[("PDF documents","*.pdf"),("All files","*.*")]))
def choose():
    index_files(filedialog.askopenfilenames(filetypes=[("Images",("*.png","*.jpg","*.jpeg","*.bmp","*.webp")),("All files","*.*")]))
def documents():
    win=tk.Toplevel(root)
    win.title("Saved Documents")
    win.geometry("850x400")
    listing=ttk.Treeview(win,columns=("name","state"),show="headings")
    listing.heading("name",text="Original document")
    listing.heading("state",text="Status")
    listing.pack(fill="both",expand=True)
    with connect() as c:
        rows=c.execute("SELECT path,name,state FROM documents ORDER BY rowid DESC").fetchall()
    for i,(_,name,state) in enumerate(rows): listing.insert("","end",iid=str(i),values=(name,state))
    def open_doc():
        if listing.selection(): os.startfile(rows[int(listing.selection()[0])][0])
    ttk.Button(win,text="Open original",command=open_doc).pack()
    ttk.Button(win,text="Open storage folder",command=lambda:os.startfile(DOCS)).pack()
def reprocess():
    if busy: return
    with connect() as c:
        paths=[p for (p,) in c.execute("SELECT path FROM documents") if Path(p).exists()]
    if paths: index_files(paths, reuse=True)
    else: messagebox.showinfo("Reprocess","No saved originals. Import the original PDF again.")
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
    row_count=0
    with connect() as c:
        docs=c.execute("SELECT count(*) FROM documents").fetchone()[0]
        pages=c.execute("SELECT id,body FROM pages").fetchall()
        for id,body in pages:
            for n,row in enumerate(parse_rows(body)):
                row_count+=1
                if matches(row,q,mode.get()):
                    order,hh,name,address=row
                    tree.insert("","end",iid=f"{id}:{n}",values=(order,name,address))
                    total+=1
    summary.set(f"Saved documents: {docs}  |  Indexed pages: {len(pages)}  |  Household records: {row_count}  |  Matches: {total}")
    status.set("No household rows recognized. Reprocess PDF or check source layout." if pages and not row_count else f"{total} matching household rows • Verify against original")
def original():
    if not tree.selection(): return
    with connect() as c:
        row=c.execute("SELECT image FROM pages WHERE id=?",(tree.selection()[0].split(':')[0],)).fetchone()
    if row: os.startfile(row[0])
def export_pdf():
    path=filedialog.asksaveasfilename(defaultextension=".pdf",filetypes=[("PDF","*.pdf")])
    if not path:return
    with connect() as c: rows=c.execute("SELECT image FROM pages ORDER BY id").fetchall()
    if not rows:
        messagebox.showwarning("Save PDF","No indexed pages. Check Saved Documents for original PDFs and import errors.")
        return
    with fitz.open() as doc:
        for (img,) in rows:
            with fitz.open(img) as image: doc.insert_pdf(fitz.open("pdf",image.convert_to_pdf()))
        doc.save(path)
    status.set("Image PDF saved")
for label,cmd in [("Capture screen",capture),("Import PDF",choose_pdf),("Import images",choose),("Saved Documents",documents),("Save all as PDF",export_pdf),("View original",original)]:
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
ttk.Label(root,textvariable=summary,font=("Segoe UI",11,"bold")).pack()
ttk.Button(root,text="Reprocess saved documents",command=reprocess).pack(pady=3)
ttk.Label(root,textvariable=status).pack()
ttk.Label(root,text="Developed by Razmi Mohamed • Verify OCR against original • Preview").pack(pady=8)
search()
root.mainloop()

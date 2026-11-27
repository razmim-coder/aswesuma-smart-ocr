import os, sys, sqlite3, threading, shutil, re, uuid
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from PIL import Image, ImageGrab, ImageOps
import fitz
import pytesseract
from household import parse_rows, matches, screenshot_rows, duplicate_ids, format_hh

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
root.title("ASWESUMA SMART OCR - V1.0.9 Preview")
root.geometry("1220x720")
root.configure(bg="#f4f5f7")
ttk.Style().theme_use("clam")
ttk.Label(root,text="ASWESUMA SMART OCR",font=("Segoe UI",24,"bold")).pack(pady=15)
bar=ttk.Frame(root); bar.pack(fill="x",padx=18)
status=tk.StringVar(value="Ready • Local storage only")
query=tk.StringVar()
mode=tk.StringVar(value='All')
summary=tk.StringVar()
eligibility=tk.StringVar(value='All')
accuracy=tk.StringVar(value='High Accuracy')
duplicates_only=tk.BooleanVar(value=False)
lang=tk.StringVar(value="eng+tam+sin")
busy=False
capturing=False
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
    high=accuracy.get()=='High Accuracy'
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
                                    save_page(c,im,path,i+1,selected,p.get_text(sort=True),p,high)
                                    count+=1
                                    notify(f"Processing page {i+1}/{len(doc)}")
                        else:
                            with Image.open(saved) as im:
                                save_page(c,im.convert("RGB"),path,1,selected,"",accuracy=high)
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
                else:
                    with connect() as check:
                        records=sum(len(list(parse_rows(body))) for (body,) in check.execute("SELECT body FROM pages"))
                    if records==0:
                        messagebox.showwarning("Saved, but no household records","Original documents saved. No recognizable household rows yet. Open Saved Documents to verify the captured source.")
                    else:
                        messagebox.showinfo("Import complete",f"Processed {count} pages. {records} household rows currently indexed. Verify against original.")
            root.after(0,finish)
        except Exception as e:
            notify("Error: "+str(e))
        finally: busy=False
    threading.Thread(target=worker,daemon=True).start()
def save_page(c,im,source,page,language,existing,pdf_page=None,accuracy=False):
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
    if accuracy or not list(parse_rows(body)):
        try:
            recognized=screenshot_rows(im,accuracy=accuracy)
            if recognized:
                body="\n".join(f"{order} HH{hh} | {name} | {address} | {category} | {status}" for order,hh,name,address,category,status in recognized)
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
    global capturing
    if busy or capturing:
        messagebox.showinfo("Capture","Please finish the current import or capture.")
        return
    status.set("Capturing in 5 seconds; switch to the Aswesuma browser window.")
    capturing=True
    root.iconify()
    def take():
        global capturing
        path=None
        try:
            image=ImageGrab.grab(all_screens=False)
            if image.width<100 or image.height<100:
                raise ValueError("Screen image is empty")
            path=BASE/("capture-"+uuid.uuid4().hex+".png")
            image.save(path)
            root.deiconify()
            root.lift()
            index_files([str(path)])
        except Exception as e:
            root.deiconify()
            messagebox.showerror("Screen capture failed",str(e)+"\nUse Windows+Shift+S, then Paste Screenshot.")
        finally:
            capturing=False
            root.deiconify()
    root.after(5000,take)
def paste_capture():
    if busy or capturing: return
    try:
        im=ImageGrab.grabclipboard()
        if not isinstance(im,Image.Image):
            messagebox.showinfo("Paste Screenshot","Use Windows+Shift+S to copy an image first.")
            return
        path=BASE/("capture-"+uuid.uuid4().hex+".png")
        im.convert("RGB").save(path)
        index_files([str(path)])
    except Exception as e:
        messagebox.showerror("Paste Screenshot",str(e))
def delete_all():
    if busy or capturing:
        messagebox.showwarning("Delete All Data","Finish import or capture first.")
        return
    if not messagebox.askyesno("Delete All Data","Permanently remove all imported PDFs, screenshots and OCR records stored inside this app? Original files outside the app will not be deleted."):
        return
    if simpledialog.askstring("Confirm deletion","Type DELETE to permanently clear the app:") != "DELETE":
        return
    failures=[]
    for folder in (PAGES,DOCS):
        for item in folder.iterdir():
            if item.is_file() or item.is_symlink():
                try: item.unlink()
                except OSError as e: failures.append(str(e))
    for item in BASE.glob("capture-*.png"):
        try: item.unlink()
        except OSError as e: failures.append(str(e))
    with connect() as c:
        c.execute("DELETE FROM pages")
        c.execute("DELETE FROM documents")
        c.commit()
    eligibility.set("All")
    duplicates_only.set(False)
    query.set("")
    search()
    if failures: messagebox.showwarning("Partial deletion","Some local files could not be removed:\n"+"\n".join(failures))
    else: messagebox.showinfo("Delete All Data","All app records and imported copies removed.")
def search(*args):
    q=query.get().strip()
    tree.delete(*tree.get_children())
    total=0
    with connect() as c:
        docs=c.execute("SELECT count(*) FROM documents").fetchone()[0]
        pages=c.execute("SELECT id,body FROM pages").fetchall()
    rows=[(id,n,row) for id,body in pages for n,row in enumerate(parse_rows(body))]
    row_count=len(rows)
    dup=duplicate_ids([row for _,_,row in rows])
    for id,n,row in rows:
        order,hh,name,address,category,eligible=row
        repeated=hh in dup
        if duplicates_only.get() and not repeated: continue
        if matches(row,q,mode.get()) and (eligibility.get()=="All" or eligible==eligibility.get()):
            tree.insert("","end",iid=f"{id}:{n}",values=(order,format_hh(hh),name,address,category,eligible),tags=(("Duplicate",eligible) if repeated else (eligible,)))
            total+=1
    summary.set(f"Saved documents: {docs}  |  Indexed pages: {len(pages)}  |  Household records: {row_count}  |  Duplicate HH IDs: {len(dup)}  |  Matches: {total}")
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
for label,cmd in [("Capture screen",capture),("Paste Screenshot",paste_capture),("Import PDF",choose_pdf),("Import images",choose),("Saved Documents",documents),("Save all as PDF",export_pdf),("View original",original)]:
    ttk.Button(bar,text=label,command=cmd).pack(side="left",padx=5)
ttk.Combobox(bar,textvariable=lang,values=["eng+tam+sin","eng","tam","sin"],state="readonly",width=15).pack(side="right")
ttk.Label(root,text="Search by HH Number / Name / House Number / Address").pack(pady=(20,3))
entry=ttk.Entry(root,textvariable=query,font=("Segoe UI",15));entry.pack(fill="x",padx=22)
selector=ttk.Combobox(root,textvariable=mode,values=["All","HH Number","Name","House Number","Address"],state="readonly")
selector.pack(pady=5)
selector.bind("<<ComboboxSelected>>",search)
elig=ttk.Combobox(root,textvariable=eligibility,values=["All","Eligible","Not Eligible","Unknown"],state="readonly")
elig.pack(pady=3)
elig.bind("<<ComboboxSelected>>",search)
controls=ttk.Frame(root)
controls.pack(pady=3)
ttk.Label(controls,text="OCR Mode:").pack(side="left",padx=4)
ttk.Combobox(controls,textvariable=accuracy,values=["Standard","High Accuracy"],state="readonly",width=15).pack(side="left",padx=4)
ttk.Checkbutton(controls,text="Show duplicate HH IDs only",variable=duplicates_only,command=search).pack(side="left",padx=12)
query.trace_add("write",search)
tree=ttk.Treeview(root,columns=("order","hh","name","address","category","status"),show="headings")
for col,w in [("order",70),("hh",170),("name",260),("address",380),("category",100),("status",110)]:
    tree.heading(col,text={"order":"Order No.","hh":"HH Number","status":"Aswesuma Status"}.get(col,col.title()));tree.column(col,width=w)
tree.tag_configure("Duplicate",background="#fff1c2")
tree.tag_configure("Eligible",foreground="#176b39")
tree.tag_configure("Not Eligible",foreground="#b42318")
tree.pack(fill="both",expand=True,padx=22,pady=10)
tree.bind("<Double-1>",lambda e:original())
ttk.Label(root,textvariable=summary,font=("Segoe UI",11,"bold")).pack()
toolsbar=ttk.Frame(root)
toolsbar.pack(pady=3)
ttk.Button(toolsbar,text="Reprocess saved documents",command=reprocess).pack(side="left",padx=5)
ttk.Button(toolsbar,text="Delete All Data",command=delete_all).pack(side="left",padx=5)
ttk.Label(root,textvariable=status).pack()
ttk.Label(root,text="Developed by Razmi Mohamed • Verify OCR against original • Preview").pack(pady=8)
search()
root.mainloop()

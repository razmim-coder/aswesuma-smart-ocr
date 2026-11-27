import re
import unicodedata

HH = re.compile(r"(?<!\w)(?:HH[\s-]*)?(\d)[\s-]*(\d)[\s-]*(\d{2})[\s-]*(\d{2})[\s-]*(\d{3})[\s-]*(\d{5})(?!\w)", re.I)
def norm(value):
    return "".join(c for c in unicodedata.normalize("NFC", value).casefold() if c.isalnum() or unicodedata.category(c).startswith("M"))
def parse_rows(text):
    """Only accept unambiguous single-line rows: order, HH, name, address.
    Never join adjacent lines or infer missing fields."""
    for line in text.splitlines():
        hits=list(HH.finditer(line))
        if len(hits)!=1: continue
        hit=hits[0]
        order=line[:hit.start()].strip(" \t|.")
        if not order.isdecimal(): continue
        tail=line[hit.end():].strip(" \t|")
        parts=tail.split("|") if "|" in tail else re.split(r"\t+| {2,}",tail)
        parts=[p.strip() for p in parts]
        if len(parts) not in (2,4): continue
        name,address=(p.strip() for p in parts[:2])
        category,status=(parts[2:] if len(parts)==4 else ('Unknown','Unknown'))
        if not name or not address or not any(c.isalpha() for c in name): continue
        yield order,"".join(hit.groups()),name,address,category,status

def matches(row, query, mode="All"):
    order,hh,name,address,category,status=row
    q=norm(query)
    if not q: return not query.strip()
    h=q.removeprefix("hh")
    hh_match=(q=="hh") or (h.isdecimal() and h in hh)
    house=re.match(r"\s*([\d][\w/-]*)",address)
    house_match=bool(house and norm(house.group(1)).startswith(q))
    name_match=q in norm(name)
    address_match=q in norm(address)
    return {"HH Number":hh_match,"Name":name_match,"House Number":house_match,"Address":address_match,"All":hh_match or name_match or address_match or house_match}[mode]

def screenshot_rows(image, accuracy=False):
    """Recognize the full-screen Aswesuma table layout using horizontal rules."""
    from PIL import Image
    import pytesseract
    if not 1.65 < image.width/image.height < 1.9:
        return []
    im=image.convert("L").resize((1440,810),Image.Resampling.LANCZOS)
    # Table borders span the blank space between address and category.
    profile=list(im.crop((950,68,1100,780)).resize((1,712)).getdata())
    groups=[]
    for y,value in enumerate(profile):
        if 210<=value<248:
            if groups and y==groups[-1][-1]+1:
                groups[-1].append(y)
            else:
                groups.append([y])
    # Keep both single-pixel and multi-pixel rules, plus the header's lower edge.
    cuts=[68+(g[-1] if len(g)>5 else round(sum(g)/len(g)))
          for g in groups if len(g)<=5 or (g[0]<15 and 20<=len(g)<=70)]
    bands=[(a,b) for a,b in zip(cuts,cuts[1:]) if 32<=b-a<=100]
    if len(bands)<5: return []
    top,bottom=bands[0][0],bands[-1][1]
    def words(left,right,scale,config):
        crop=im.crop((left,top,right,bottom)).resize(((right-left)*scale,(bottom-top)*scale),Image.Resampling.LANCZOS)
        d=pytesseract.image_to_data(crop,lang="eng",config=config,output_type=pytesseract.Output.DICT)
        out=[]
        for i,t in enumerate(d["text"]):
            if t.strip():
                out.append((left+d["left"][i]/scale,top+(d["top"][i]+d["height"][i]/2)/scale,t))
        return out
    orders=words(120,165,4,"--psm 6 -c tessedit_char_whitelist=0123456789")
    content=words(166,1315,3,"--psm 11")
    focused=words(166,280,5,"--psm 6 -c tessedit_char_whitelist=HH0123456789-") if accuracy else []
    rows=[]
    for a,b in bands:
        order="".join(t for x,y,t in orders if a<y<b)
        if not order.isdecimal(): continue
        def cell(lo,hi):
            ws=[(x,y,t) for x,y,t in content if a<y<b and lo<=x<hi]
            return " ".join(t for x,y,t in sorted(ws,key=lambda w:(round(w[1]/9),w[0])))
        ref=cell(166,280)
        # Reference is wrapped over two physical lines.
        ref=re.sub(r"\s+","",ref)
        h=HH.fullmatch(ref)
        if accuracy:
            alternate="".join(t for x,y,t in sorted((w for w in focused if a<w[1]<b),key=lambda w:(round(w[1]/9),w[0])))
            alt=HH.fullmatch(alternate)
            if h is None and alt is not None:
                h=alt
            elif h and alt and h.groups()!=alt.groups():
                crop=im.crop((166,a+1,280,b-1)).resize((570,max(1,(b-a-2)*5)),Image.Resampling.LANCZOS)
                third=HH.fullmatch(re.sub(r"\s+","",pytesseract.image_to_string(crop,lang="eng",config="--psm 6 -c tessedit_char_whitelist=HH0123456789-")))
                if third and third.groups()==alt.groups(): h=alt
        name=cell(280,600); address=cell(600,1125)
        if h and name and address and any(c.isalpha() for c in name):
            category=cell(1125,1205) or "Unknown"
            raw=norm(cell(1205,1315))
            status={"eligible":"Eligible","noteligible":"Not Eligible"}.get(raw,"Unknown")
            rows.append((order,"".join(h.groups()),name,address,category,status))
    return rows

def duplicate_ids(rows):
    from collections import Counter
    counts=Counter(norm(row[1]).removeprefix("hh") for row in rows if row[1])
    return {hh:n for hh,n in counts.items() if n>1}

def format_hh(hh):
    if len(hh)==14 and hh.isdecimal():
        return "HH-"+ "-".join((hh[0:1],hh[1:2],hh[2:4],hh[4:6],hh[6:9],hh[9:14]))
    return "HH"+hh

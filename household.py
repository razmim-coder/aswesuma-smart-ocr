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
    """Detect table rules and adapt column positions to the observed table width."""
    from PIL import Image
    from statistics import median
    import pytesseract as t
    if not 1.65 < image.width/image.height < 1.9:
        return []
    im=image.convert("L").resize((1440,810),Image.Resampling.LANCZOS)
    profile=list(im.crop((950,68,1100,780)).resize((1,712)).getdata())
    groups=[]
    for y,v in enumerate(profile):
        if 210<=v<248:
            if groups and y==groups[-1][-1]+1: groups[-1].append(y)
            else: groups.append([y])
    cuts=[68+(g[-1] if len(g)>5 else round(sum(g)/len(g))) for g in groups
          if len(g)<=5 or (g[0]<15 and 20<=len(g)<=70)]
    bands=[(a,b) for a,b in zip(cuts,cuts[1:]) if 32<=b-a<=100]
    if len(bands)<5: return []
    bounds=[]
    for y in cuts:
        runs=[]
        for x,v in enumerate(im.crop((0,y,1440,y+1)).getdata()):
            if 210<=v<248:
                if runs and x==runs[-1][-1]+1: runs[-1].append(x)
                else: runs.append([x])
        valid=[g for g in runs if len(g)>700]
        if valid:
            g=max(valid,key=len)
            bounds.append((g[0],g[-1]))
    if len(bounds)<3: return []
    left=median([a for a,b in bounds])
    right=median([b for a,b in bounds])
    def mapped(x):
        return round(left+(x-113)*(right-left)/1201)
    top,bottom=bands[0][0],bands[-1][1]
    def col(left,right,scale,config):
        left,right=mapped(left),mapped(right)
        crop=im.crop((left,top,right,bottom)).resize(((right-left)*scale,(bottom-top)*scale),Image.Resampling.LANCZOS)
        d=t.image_to_data(crop,lang="eng",config=config,output_type=t.Output.DICT)
        return [(d["left"][i]/scale,top+(d["top"][i]+d["height"][i]/2)/scale,word) for i,word in enumerate(d["text"]) if word.strip()]
    def read(ws,a,b):
        lines=[]
        for x,y,w in sorted((w for w in ws if a<w[1]<b),key=lambda w:w[1]):
            if lines and abs(y-lines[-1][0])<5: lines[-1][1].append((x,w))
            else: lines.append((y,[(x,w)]))
        return " ".join(" ".join(w for x,w in sorted(line)) for y,line in lines)
    order_config="--psm 6 -c tessedit_char_whitelist=0123456789"
    ref_config="--psm 6 -c tessedit_char_whitelist=HH0123456789-"
    orders=col(120,165,4,order_config)
    refs=col(166,280,4,ref_config)
    names=col(280,600,3,"--psm 6")
    addresses=col(600,1125,3,"--psm 6")
    statuses=col(1210,1310,4,"--psm 6")
    cats=col(1125,1210,3,"--psm 6")
    rows=[]
    for a,b in bands:
        order=read(orders,a,b).replace(" ","")
        ref=read(refs,a,b)
        name=read(names,a,b)
        addr=read(addresses,a,b)
        raw_status=read(statuses,a,b)
        cat=read(cats,a,b)
        def retry(left,right,config):
            left,right=mapped(left),mapped(right)
            crop=im.crop((left,a+2,right,b-2)).resize(((right-left)*5,max(1,(b-a-4)*5)),Image.Resampling.LANCZOS)
            return " ".join(t.image_to_string(crop,lang="eng",config=config).split())
        def ref_digits(value):
            # Accept only recognized digits, HH and punctuation; do not guess missing digits.
            return re.fullmatch(r"(?:HH)?(\d{14})",re.sub(r"[\s-]","",value.upper()))
        h=ref_digits(ref)
        if accuracy:
            if not order.isdecimal(): order=retry(120,165,"--psm 7 -c tessedit_char_whitelist=0123456789")
            if not h: h=ref_digits(retry(166,280,ref_config))
            if not name: name=retry(280,600,"--psm 6")
            if not addr: addr=retry(600,1125,"--psm 6")
        if order.isdecimal() and h and name and addr and any(c.isalpha() for c in name):
            status={"eligible":"Eligible","noteligible":"Not Eligible"}.get(norm(raw_status),"Unknown")
            rows.append((order,h.group(1),name,addr,cat or "Unknown",status))
    return rows

def duplicate_ids(rows):
    from collections import Counter
    counts=Counter(norm(row[1]).removeprefix("hh") for row in rows if row[1])
    return {hh:n for hh,n in counts.items() if n>1}

def format_hh(hh):
    if len(hh)==14 and hh.isdecimal():
        return "HH-"+ "-".join((hh[0:1],hh[1:2],hh[2:4],hh[4:6],hh[6:9],hh[9:14]))
    return "HH"+hh

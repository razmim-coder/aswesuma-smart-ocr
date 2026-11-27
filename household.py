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
        parts=re.split(r"\t+|\s*\|\s*| {2,}",tail)
        if len(parts)!=2: continue
        name,address=(p.strip() for p in parts)
        if not name or not address or not any(c.isalpha() for c in name): continue
        yield order,"".join(hit.groups()),name,address

def matches(row, query, mode="All"):
    order,hh,name,address=row
    q=norm(query)
    if not q: return not query.strip()
    h=q.removeprefix("hh")
    hh_match=h.isdecimal() and (hh==h or (len(h)<=5 and hh.endswith(h)))
    house=re.match(r"\s*([\d][\w/-]*)",address)
    house_match=bool(house and norm(house.group(1)).startswith(q))
    name_match=q in norm(name)
    address_match=q in norm(address)
    return {"HH Number":hh_match,"Name":name_match,"House Number":house_match,"Address":address_match,"All":hh_match or name_match or address_match or house_match}[mode]

import re
from statistics import median
from PIL import Image, ImageOps
import pytesseract as t

def cropped_table_rows(image, accuracy=False):
    w,h=image.size
    if not 1.15<w/h<1.60:return []
    im=image.convert('L')
    # A cropped Aswesuma table has full-width horizontal rules and no browser chrome.
    profile=list(im.crop((int(w*.80),0,int(w*.84),h)).resize((1,h)).getdata())
    groups=[]
    for y,v in enumerate(profile):
        if 210<=v<248:
            if groups and y==groups[-1][-1]+1:groups[-1].append(y)
            else:groups.append([y])
    cuts=[round(sum(g)/len(g)) for g in groups if len(g)<=max(3,round(w*.005))]
    if len(cuts)<4:return []
    gaps=[b-a for a,b in zip(cuts,cuts[1:]) if .025*w<b-a<.065*w]
    if len(gaps)<3:return []
    step=median(gaps)
    if cuts[0]<.25*step:cuts[0]=0
    elif .80*step<=cuts[0]<=1.25*step:cuts.insert(0,0)
    if h-cuts[-1]<.25*step:cuts[-1]=h
    elif .80*step<=h-cuts[-1]<=1.25*step:cuts.append(h)
    bands=[(a,b) for a,b in zip(cuts,cuts[1:]) if .70*step<=b-a<=1.30*step]
    if len(bands)<3:return []
    top,bottom=bands[0][0],bands[-1][1]
    def col(l,r,config):
        l,r=round(l*w),round(r*w)
        crop=im.crop((l,top,r,bottom));scale=max(1,2600/w)
        crop=crop.resize((round(crop.width*scale),round(crop.height*scale)),Image.Resampling.LANCZOS)
        d=t.image_to_data(crop,lang='eng',config=config,output_type=t.Output.DICT)
        return [(d['left'][i]/scale,top+(d['top'][i]+d['height'][i]/2)/scale,word) for i,word in enumerate(d['text']) if word.strip()]
    def read(ws,a,b):
        lines=[]
        for x,y,word in sorted((v for v in ws if a< v[1]<b),key=lambda v:v[1]):
            if lines and abs(y-lines[-1][0])<step*.13:lines[-1][1].append((x,word))
            else:lines.append((y,[(x,word)]))
        return ' '.join(' '.join(word for x,word in sorted(line)) for y,line in lines)
    cfg='--psm 6'
    oc=cfg+' -c tessedit_char_whitelist=0123456789'
    hc=cfg+' -c tessedit_char_whitelist=HH0123456789-'
    specs=[(0,.043,oc),(.044,.14,hc),(.14,.405,cfg),(.407,.844,cfg),(.845,.916,cfg),(.917,1,cfg)]
    cols=[col(*spec) for spec in specs]
    rows=[]
    for a,b in bands:
        vals=[read(ws,a,b) for ws in cols]
        order,ref,name,address,category,status=vals
        def digits(ref):return re.fullmatch(r'(?:HH)?(\d{14})',re.sub(r'[\s-]','',ref.upper()))
        order=order.replace(' ',''); hh=digits(ref)
        if accuracy and (not hh or not order.isdecimal()):
            for k in ([0] if not order.isdecimal() else [])+([1] if not hh else []):
                l,r,c=specs[k];crop=im.crop((round(l*w),a+2,round(r*w),b-2));crop=crop.resize((crop.width*3,crop.height*3),Image.Resampling.LANCZOS)
                v=t.image_to_string(crop,lang='eng',config=c)
                if k==0:order=''.join(v.split())
                else:hh=digits(v)
        status={'eligible':'Eligible','noteligible':'Not Eligible'}.get(re.sub(r'[^a-z]','',status.lower()),'Unknown')
        if order.isdecimal() and hh and name and address:rows.append((order,hh.group(1),name,address,category or 'Unknown',status))
    return rows

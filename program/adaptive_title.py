"""Keep readable title sizes, wrap/page all text within the source safe area."""
import math
from publish_style import line_parts,units,clusters

def plan(text,size,x,y,box,vertical=False,side=False,glyph_ratio=1,advance=0):
    vx,vy,vw,vh=box;left=vx+12;right=vx+vw-12;bottom=vy+vh-12
    requested=size;notes=[]
    # Only reduce when a single readable glyph cannot fit, never to pack all text.
    limit=min((right-left)/1.1,(bottom-(vy+12))/1.25)
    size=max(18,min(size,math.floor(limit)))
    if size<requested:notes.append(f'单字超出安全区，字号由{requested}调整为{size}')
    y=min(max(vy+12,y),bottom-size*1.25)
    if vertical:
        glyph=max(12,size*glyph_ratio);step=advance if advance>0 and size==requested else glyph*1.35
        step=max(glyph,step);x=min(max(left+glyph/2,x),right-glyph/2)
        capacity=max(1,math.floor((bottom-y-glyph)/step)+1)
        cols=max(1,min(5,math.floor((right-x-glyph/2)/(glyph*1.35))+1))
        chars=[c for _,c in clusters(text) if not c.isspace()]
        chunks=[chars[i:i+capacity] for i in range(0,len(chars),capacity)]
        pages=[chunks[i:i+cols] for i in range(0,len(chunks),cols)]
        result=[]
        for columns in pages:
            # Read columns right to left; stay on the right of the original title.
            result.append(dict(columns=[dict(text=''.join(col),x=x+(len(columns)-1-i)*glyph*1.35) for i,col in enumerate(columns)],weight=sum(map(len,columns))))
        return dict(size=size,x=x,y=y,pages=result,step=step,notes=notes)
    if side:
        x=min(max(left,x),right-size*1.2);available=right-x
    else:
        x=min(max(left+size*.7,x),right-size*.7);available=min(vw*.88,2*min(x-left,right-x))
    if available<size*1.1+12:
        # A usable safe-area block, rather than repeatedly shrinking the font.
        x=left if side else vx+vw/2;available=right-left if side else vw*.88
        notes.append('译名横向空间过窄，已调整到画面安全区')
    rows=max(1,min(5,math.floor((bottom-y)/(size*1.25))))
    lines=line_parts(text,max(1,(available-12)/(size*1.1)))
    pages=[]
    for i in range(0,len(lines),rows):
        page=lines[i:i+rows];pages.append(dict(lines=[''.join(c for _,c in row) for row in page],weight=max(1,sum(units(''.join(c for _,c in row)) for row in page))))
    return dict(size=size,x=x,y=y,pages=pages,notes=notes)

def times(pages,start,end):
    total=sum(p['weight'] for p in pages);elapsed=0;result=[]
    for index,page in enumerate(pages):
        a=start+(end-start)*elapsed/total;elapsed+=page['weight'];b=end if index==len(pages)-1 else start+(end-start)*elapsed/total
        if len(pages)>1 and b-a<1:page['short_time']=True
        result.append((a,b,page))
    return result

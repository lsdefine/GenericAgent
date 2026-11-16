"""Small local icon classifier. No neural model or network at runtime."""
from pathlib import Path
import copy
import cv2
import numpy as np
from PIL import Image
ROOT=Path(__file__).resolve().parent
LABELS={'search':'search','settings':'settings','x':'close','arrow-left':'back','menu':'menu','refresh-cw':'refresh'}

def feature(image):
    a=np.asarray(image.convert('RGB'))
    if a.size==0:return None
    g=cv2.cvtColor(a,cv2.COLOR_RGB2GRAY)
    # Dominant background, not the median border (hover regions may touch borders).
    bg=int(np.argmax(np.bincount(g.ravel(),minlength=256)))
    delta=np.abs(g.astype(np.float32)-bg)
    if delta.max()<15:return None
    mask=(delta>max(10,float(np.percentile(delta[delta>0],90))*.35)).astype(np.uint8)
    n,lab,stats,_=cv2.connectedComponentsWithStats(mask)
    h,w=mask.shape
    for i,(x,y,cw,ch,area) in enumerate(stats[1:],1):
        touches=x==0 or y==0 or x+cw==w or y+ch==h
        if area<3 or (touches and (cw>w*.8 or ch>h*.8 or area<12)):
            mask[lab==i]=0
    ys,xs=np.where(mask)
    if len(xs)<5:return None
    mask=mask[ys.min():ys.max()+1,xs.min():xs.max()+1]
    h,w=mask.shape;scale=40/max(h,w)
    norm=cv2.resize(mask.astype(np.float32),(max(1,round(w*scale)),max(1,round(h*scale))))
    out=np.zeros((48,48),np.float32);y=(48-norm.shape[0])//2;x=(48-norm.shape[1])//2
    out[y:y+norm.shape[0],x:x+norm.shape[1]]=norm
    out=cv2.GaussianBlur(out,(5,5),1.0).ravel()
    return out/(np.linalg.norm(out)+1e-8)

class IconLabeler:
    def __init__(self, bank=None, threshold=.90, margin=.045):
        self.threshold,self.margin=threshold,margin
        with np.load(bank or ROOT/'icon_templates.npz',allow_pickle=False) as data:
            self.names=data['names'];self.matrix=data['features']
        self.groups={n:np.flatnonzero(self.names==n) for n in set(self.names)}
    def classify(self,crop):
        f=feature(crop)
        if f is None:return None,0.,0.
        scores=np.einsum('ij,j->i',self.matrix,f,optimize=False)
        ranked=sorted(((n,float(scores[ix].max())) for n,ix in self.groups.items()),key=lambda p:p[1],reverse=True)
        name,score=ranked[0];gap=score-ranked[1][1]
        label=LABELS.get(name) if score>=self.threshold and gap>=self.margin else None
        return label,round(score,4),round(gap,4)
    def enhance(self,image,elements):
        im=image.convert('RGB') if isinstance(image,Image.Image) else Image.open(image).convert('RGB')
        result=copy.deepcopy(elements)
        for el in result:
            if el.get('type')!='icon':continue
            x1,y1,x2,y2=el['bbox'];w=x2-x1;h=y2-y1
            if min(w,h)<8 or max(w,h)>160 or not .3<w/h<3.3:continue
            crop=im.crop((max(0,x1-2),max(0,y1-2),min(im.width,x2+2),min(im.height,y2+2)))
            name,score,gap=self.classify(crop)
            if name:
                el.update(icon_name=name,icon_score=score,icon_margin=gap,icon_source='template')
                if not el.get('label'):el.update(label=name,label_source='icon_template')
        return result

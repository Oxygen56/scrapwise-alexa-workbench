import sys, json, math, time, hashlib, random, itertools, argparse
from pathlib import Path
from datetime import datetime, timezone

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'vendor'))
import pyclipper
import shapely
from shapely.geometry import Polygon
from shapely import affinity

ROOT = HERE.parents[3]
CONTRACT = ROOT / 'reports/scrapwise-first-proof/contract.json'
CONTRACT_HASH = '681813f7d2e65cd73b3c3ca67ef850caf0882a48cb35715effcee4d3a4fed025'
SCALE = 100000
EPS = 0.00004
NFP_CACHE = {}

def utc(): return datetime.now(timezone.utc).isoformat()
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def orientations(part):
    out = []
    for angle in part['allowedRotations']:
        a=math.radians(angle);c=round(math.cos(a));s=round(math.sin(a))
        pts=[(c*x-s*y,s*x+c*y) for x,y in part['vertices']]
        lx=min(x for x,y in pts);ly=min(y for x,y in pts)
        pts=[(x-lx,y-ly) for x,y in pts]
        poly=Polygon(pts)
        path=[(round(x*SCALE),round(y*SCALE)) for x,y in pts]
        if not pyclipper.Orientation(path): path.reverse()
        out.append({'angle':angle,'points':pts,'poly':poly,'path':path,'width':poly.bounds[2],'height':poly.bounds[3],'key':(part['id'],angle)})
    return out

def nfp(ob, target, spacing):
    key=(ob['key'],target['key'],spacing)
    if key in NFP_CACHE: return NFP_CACHE[key]
    off=pyclipper.PyclipperOffset(2,0.25*SCALE)
    off.AddPath(ob['path'],pyclipper.JT_MITER,pyclipper.ET_CLOSEDPOLYGON)
    expanded=off.Execute((spacing+EPS)*SCALE)
    paths=[]
    pattern=[(-x,-y) for x,y in target['path']]
    for p in expanded:
        sums=pyclipper.MinkowskiSum(pattern,p,True)
        if sums:
            q=max(sums,key=lambda z:abs(pyclipper.Area(z)))
            if not pyclipper.Orientation(q): q.reverse()
            paths.append(q)
    NFP_CACHE[key]=paths
    return paths

def candidates(target, sheet, placed, spacing, margin):
    lo=round((margin+EPS)*SCALE)
    xmax=math.floor((sheet['width']-margin-target['width']-EPS)*SCALE)
    ymax=math.floor((sheet['height']-margin-target['height']-EPS)*SCALE)
    if xmax<lo or ymax<lo:return []
    subject=[(lo,lo),(xmax,lo),(xmax,ymax),(lo,ymax)]
    clips=[]
    for ob in placed:
        dx=round(ob['x']*SCALE);dy=round(ob['y']*SCALE)
        for p in nfp(ob['o'],target,spacing):
            clips.append([(x+dx,y+dy) for x,y in p])
    if clips:
        pc=pyclipper.Pyclipper();pc.AddPath(subject,pyclipper.PT_SUBJECT,True)
        pc.AddPaths(clips,pyclipper.PT_CLIP,True)
        free=pc.Execute(pyclipper.CT_DIFFERENCE,pyclipper.PFT_NONZERO,pyclipper.PFT_NONZERO)
    else:free=[subject]
    points=set((x/SCALE,y/SCALE) for p in free for x,y in p)
    return sorted(points,key=lambda v:(v[1],v[0]))

def greedy(instances,sheets,variants,spacing,margin,mode):
    bins=[[] for s in sheets]
    for part,copy in instances:
        chosen=None
        for bi,sheet in enumerate(sheets):
            options=[]
            for o in variants[part['id']]:
                for x,y in candidates(o,sheet,bins[bi],spacing,margin):
                    if mode=='bottom':score=(y,x,y+o['height'],x+o['width'])
                    elif mode=='height':score=(y+o['height'],x+o['width'],y,x)
                    else:score=((x+o['width'])*(y+o['height']),y+o['height'],x+o['width'])
                    options.append((score,o,x,y))
            options.sort(key=lambda z:z[0])
            for score,o,x,y in options:
                poly=affinity.translate(o['poly'],x,y)
                if any(poly.distance(ob['poly']) < spacing-1e-8 for ob in bins[bi]):continue
                chosen={'part':part,'copy':copy,'o':o,'x':x,'y':y,'poly':poly};break
            if chosen is not None:
                bins[bi].append(chosen);break
        if chosen is None:return None, len(instances)-sum(map(len,bins))
    return bins,0

def stock_options(job):
    existing=[];purchased=[]
    for s in job['stock']:
        for i in range(s['quantity']):
            t=dict(s,sheetId=f"{s['id']}--{i}",stockId=s['id'],stockInstance=i)
            (existing if s['kind']=='existing' else purchased).append(t)
    options=[]
    # All existing sheets are identical in this frozen contract. Choosing first k
    # is symmetry reduction, not dropping any available geometry/quantity.
    for np in range(len(purchased)+1):
        for ne in range(len(existing)+1):
            if not np and not ne:continue
            sheets=purchased[:np]+existing[:ne]
            pa=sum(s['width']*s['height'] for s in purchased[:np])
            ta=sum(s['width']*s['height'] for s in sheets)
            options.append((pa,ta,sheets))
    return sorted(options,key=lambda z:(z[0],z[1]))

def order_items(items,seed):
    rng=random.Random(seed)
    mode=seed%5
    def key(item):
        p=item[0];pts=p['vertices'];w=max(x for x,y in pts);h=max(y for x,y in pts)
        if mode==0:value=p['area']
        elif mode==1:value=max(w,h)
        elif mode==2:value=w*h
        elif mode==3:value=Polygon(pts).length
        else:value=p['area']*(1+rng.uniform(-.25,.25))
        return -value,rng.random()
    return sorted(items,key=key)

def validate(job,sheets,bins):
    got=set();minimum=math.inf
    for sheet,placed in zip(sheets,bins):
        for i,p in enumerate(placed):
            ident=(p['part']['id'],p['copy']);assert ident not in got;got.add(ident)
            x0,y0,x1,y1=p['poly'].bounds
            assert min(x0,y0)>=job['margin']-1e-7
            assert x1<=sheet['width']-job['margin']+1e-7 and y1<=sheet['height']-job['margin']+1e-7
            assert p['o']['angle'] in p['part']['allowedRotations']
            assert abs(p['poly'].area-p['part']['area'])<1e-4
            for q in placed[:i]:
                d=p['poly'].distance(q['poly']);minimum=min(minimum,d)
                assert d>=job['spacing']-1e-7,(ident,d)
    expected={(p['id'],i) for p in job['parts'] for i in range(p['quantity'])}
    assert got==expected
    return {'allPartsPresent':True,'partGeometryPreserved':True,'allowedRotations':True,'stockQuantities':True,'margin':True,'minimumPairDistance':minimum,'spacing':True,'method':'Own Shapely geometry validation, not parent independent check'}

def export(job,input_hash,sheets,bins,out,details):
    out.mkdir(parents=True,exist_ok=True)
    sh=[];ps=[];svg=[];yoff=0;display_width=max(s['width'] for s in sheets)
    for sheet,placed in zip(sheets,bins):
        if not placed:continue
        sh.append({k:sheet[k] for k in ['sheetId','stockId','stockInstance','width','height']})
        svg.append(f'<g data-sheet-id="{sheet["sheetId"]}" transform="translate(0 {yoff})"><rect x="0" y="0" width="{sheet["width"]}" height="{sheet["height"]}" fill="none" stroke="#888"/>')
        for p in placed:
            ps.append({'partId':p['part']['id'],'copyIndex':p['copy'],'sheetId':sheet['sheetId'],'rotation':p['o']['angle'],'x':p['x'],'y':p['y']})
            pts=' '.join(f'{x+p["x"]:.8f},{y+p["y"]:.8f}' for x,y in p['o']['points'])
            svg.append(f'<polygon data-part-id="{p["part"]["id"]}" data-copy-index="{p["copy"]}" points="{pts}" fill="none" stroke="#111" stroke-width="0.15"/>')
        svg.append('</g>');yoff+=sheet['height']+20
    (out/'layout.svg').write_text(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {display_width} {yoff}">\n'+ '\n'.join(svg)+'\n</svg>\n')
    (out/'placements.json').write_text(json.dumps({'caseId':job['caseId'],'inputSha256':input_hash,'sheets':sh,'placements':ps},indent=2)+'\n')
    (out/'result.json').write_text(json.dumps(details,indent=2)+'\n')

def solve(record,attempts):
    path=ROOT/record['artifact'];input_hash=sha(path);assert input_hash==record['sha256']
    job=json.loads(path.read_text());start=time.perf_counter();started=utc()
    variants={p['id']:orientations(p) for p in job['parts']}
    items=[(p,i) for p in job['parts'] for i in range(p['quantity'])]
    # Rounded-disk offsets give a conservative numeric area bound. They are
    # disjoint for spacing=2 and fit within stock when margin=1.
    lower=sum(Polygon(p['vertices']).buffer(job['spacing']/2,quad_segs=64).area*p['quantity'] for p in job['parts'])
    history=[];answer=None
    for pa,ta,sheets in stock_options(job):
        if ta<lower-1e-6:
            history.append({'purchasedArea':pa,'totalArea':ta,'status':'OFFSET_AREA_LOWER_BOUND_SKIP'});continue
        for seed in range(attempts):
            mode=['bottom','height','area'][(seed//5)%3]
            t=time.perf_counter()
            bins,remaining=greedy(order_items(items,seed),sheets,variants,job['spacing'],job['margin'],mode)
            row={'purchasedArea':pa,'totalArea':ta,'seed':seed,'mode':mode,'seconds':time.perf_counter()-t,'placed':len(items)-remaining,'required':len(items),'status':'FEASIBLE' if bins else 'INCOMPLETE'}
            history.append(row)
            print(json.dumps({'case':job['caseId'],**row}),flush=True)
            if bins:
                validation=validate(job,sheets,bins)
                answer=(sheets,bins,pa,ta,validation);break
        if answer:break
    elapsed=time.perf_counter()-start
    out=HERE/'polygon-control'/job['caseId'];out.mkdir(parents=True,exist_ok=True)
    (out/'attempts.json').write_text(json.dumps(history,indent=2)+'\n')
    details={'caseId':job['caseId'],'inputSha256':input_hash,'contractSha256':CONTRACT_HASH,'startedAt':started,'finishedAt':utc(),'scriptCaseSeconds':elapsed,'solver':'Pyclipper no-fit-polygon search with multiple order/placement modes and Shapely legality checks','packages':{'shapely':shapely.__version__,'pyclipper':pyclipper.__version__},'offsetAreaLowerBound':lower,'optimalityClaim':'NONE; best complete legal output found; skipped insufficient-area stock sets only','candidateRead':False,'attemptCount':sum('seed' in h for h in history),'status':'COMPLETE' if answer else 'NO_COMPLETE_OUTPUT'}
    if answer:
        sheets,bins,pa,ta,validation=answer
        used=[s for s,b in zip(sheets,bins) if b]
        pa=sum(s['width']*s['height'] for s in used if s['kind']=='purchase');ta=sum(s['width']*s['height'] for s in used)
        details.update(purchasedArea=pa,totalUsedSheetArea=ta,usedSheets=len(used),placedParts=len(items),ownValidation=validation)
        export(job,input_hash,sheets,bins,out,details)
    else:(out/'result.json').write_text(json.dumps(details,indent=2)+'\n')
    return details

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--attempts',type=int,default=18);parser.add_argument('--case');args=parser.parse_args()
    assert sha(CONTRACT)==CONTRACT_HASH
    c=json.loads(CONTRACT.read_text());start=time.perf_counter();results=[]
    for r in c['caseRecords']:
        if not args.case or r['id']==args.case:results.append(solve(r,args.attempts))
    (HERE/'polygon-control').mkdir(exist_ok=True)
    (HERE/'polygon-control'/'run-summary.json').write_text(json.dumps({'recordedAt':utc(),'scriptTotalSeconds':time.perf_counter()-start,'results':results},indent=2)+'\n')
    print(json.dumps({'summary':results}),flush=True)
    return 0 if all(r['status']=='COMPLETE' for r in results) else 2
if __name__=='__main__':sys.exit(main())

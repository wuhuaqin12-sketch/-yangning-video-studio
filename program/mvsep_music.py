"""Explicit MVSep DnR v3 cloud adapter. Never falls back to local separation.
Official contract: https://mvsep.com/en/full_api (2026-11-14).
Tokens are memory-only; receipts contain no credentials.
"""
import hashlib,json,re,uuid,urllib.request,urllib.parse,urllib.error
from pathlib import Path
from media import run,probe,executable,Cancelled
API='https://mvsep.com/api/'
OPTIONS=dict(sep_type='56',add_opt1='2',add_opt2='0',add_opt3='0',output_format='1',is_demo='0')
class CloudError(RuntimeError): pass

def safe_url(url):
    p=urllib.parse.urlsplit(url)
    if p.scheme!='https' or not (p.hostname=='mvsep.com' or (p.hostname or '').endswith('.mvsep.com')) or p.username or p.password:
        raise CloudError('MVSep 返回了未经验证的下载地址；已停止，不切换模型。')
    return url
class Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        safe_url(newurl)
        # Never replay an upload on ambiguous 301/302 redirects.
        return super().redirect_request(req,fp,code,msg,headers,newurl)

def request_json(endpoint,params=None,body=None,headers=None):
    url=API+endpoint
    if params:url+='?'+urllib.parse.urlencode(params)
    req=urllib.request.Request(url,data=body,headers=headers or {})
    try:
        with urllib.request.build_opener(Redirect()).open(req,timeout=60) as r:return json.load(r)
    except urllib.error.HTTPError as e:raise CloudError(f'MVSep HTTP {e.code}；检查 API 权限、额度和网络；不会切换其他模型。') from None
    except Exception:raise CloudError('MVSep 网络请求失败或响应无法读取；若上传已开始，请先在官网核对任务，避免重复扣费。') from None

def message(d):
    data=d.get('data') or {}
    return str(data.get('message') or d.get('message') or '官方 API 未返回详细原因') if isinstance(data,dict) else '官方 API 拒绝请求'

def verify_model(payload):
    rows=payload.get('data',[]) if isinstance(payload,dict) else payload
    model=next((x for x in rows if str(x.get('render_id'))=='56'),None)
    if not model or 'dnr v3' not in model.get('name','').lower():raise CloudError('官方 API 未提供指定 DnR v3 模型；已停止。')
    fields={x['name']:x for x in model.get('algorithm_fields',[])}
    for field,key,words in [('add_opt1','2',('mel','scnet')),('add_opt2','0',('direct','mixture'))]:
        options=fields.get(field,{}).get('options',{})
        if isinstance(options,str):options=json.loads(options)
        label=str(options.get(key,'')).lower()
        if not all(w in label for w in words):raise CloudError('官方模型选项发生变化；无法确认同款方案，已停止。')
    return model

def check_account(token,progress):
    if not token.strip():raise CloudError('请在窗口输入 MVSep API Token（仅在本次会话使用）。')
    model=verify_model(request_json('app/algorithms'))
    account=request_json('app/user',{'api_token':token})
    if not account.get('success'):raise CloudError(message(account).replace(token,'[Token]'))
    d=account['data'];balance=d.get('premium_minutes','未知');enabled=str(d.get('premium_enabled'))=='1'
    progress(f'账户：剩余额度 {balance} credits；付费额度使用'+('已开启' if enabled else '未开启')+'。不会更改账户付费开关。')
    if str(model.get('orientation'))=='2' and not enabled:raise CloudError('该模型需要 Premium 权限；请先在 MVSep 官网确认，不会自动开启付费。')
    return d

def fingerprint(path,cancel):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        while True:
            if cancel.is_set():raise Cancelled('已停止')
            b=f.read(1024*1024)
            if not b:break
            h.update(b)
    return h.hexdigest()

def music_file(files):
    if not isinstance(files,list):raise CloudError('官方 Music 文件列表格式未知。')
    matches=[]
    for f in files:
        if not isinstance(f,dict):continue
        label=str(f.get('type') or f.get('stem') or f.get('name') or '')
        url=f.get('url')
        # Filename fallback is anchored at the final stem, never arbitrary substring.
        name=urllib.parse.unquote(urllib.parse.urlsplit(str(url)).path).rsplit('/',1)[-1]
        if label.strip().lower()=='music' or re.search(r'(?:^|[_ (\-])music\)?\.(?:wav|flac)$',name,re.I):
            if url:matches.append(safe_url(url))
    if len(matches)!=1:raise CloudError('无法唯一确认 Music 音乐轨；舍弃 Speech/Sfx，已停止。')
    return matches[0]

class Upload:
    def __init__(self,head,path,tail,cancel,progress):self.head=head;self.path=path;self.tail=tail;self.cancel=cancel;self.progress=progress
    def __iter__(self):
        yield self.head
        size=self.path.stat().st_size;sent=0;last=-1
        with self.path.open('rb') as f:
            while True:
                if self.cancel.is_set():raise Cancelled('停止本地上传；请到官网核对云端任务。')
                b=f.read(256*1024)
                if not b:break
                sent+=len(b);pct=int(sent*100/max(1,size))
                if pct//10!=last:self.progress(f'上传原始音轨 {pct}%');last=pct//10
                yield b
        yield self.tail

def submit(audio,token,cancel,progress):
    boundary='YangNing'+uuid.uuid4().hex
    fields=dict(OPTIONS,api_token=token)
    head=b''
    for k,v in fields.items():head+=f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    head+=f'--{boundary}\r\nContent-Disposition: form-data; name="audiofile"; filename="original.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode()
    tail=f'\r\n--{boundary}--\r\n'.encode()
    return request_json('separation/create',body=Upload(head,audio,tail,cancel,progress),headers={'Content-Type':'multipart/form-data; boundary='+boundary,'Content-Length':str(len(head)+audio.stat().st_size+len(tail))})

def video_digest(path,cancel):
    return run([executable('ffmpeg'),'-v','error','-i',str(path),'-map','0:v:0','-c:v','copy','-f','hash','-hash','sha256','-'],cancel).strip()

def process(source,folder,token,cancel,progress,seconds=None,start=0,allow_charges=False):
    source=Path(source).resolve();folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    if source.with_suffix('.mvsep.json').exists():raise CloudError('这是已分离成品，请重新选择原始视频，不叠加分离。')
    if not source.is_file():raise CloudError('原始视频不存在。')
    meta=probe(source,cancel);duration=float(meta['format']['duration'])
    if not any(x['codec_type']=='audio' for x in meta['streams']):raise CloudError('原视频没有音轨。')
    start=float(start)
    if start<0 or start>=duration:raise CloudError('试听开始位置超出原视频。')
    length=min(float(seconds),duration-start) if seconds else duration
    if not seconds and start:raise CloudError('完整处理必须从原视频 0 秒开始。')
    identity={'original_sha256':fingerprint(source,cancel),'start':start,'seconds':length,'options':OPTIONS}
    key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    cache=folder/'.mvsep_cache'/key;cache.mkdir(parents=True,exist_ok=True)
    receipt=cache/'job.json';state=json.loads(receipt.read_text()) if receipt.exists() else dict(identity)
    save=lambda:receipt.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf8')
    if not state.get('hash'):
        if state.get('submission_started'):raise CloudError('上次提交结果不明确，禁止自动重发。请先在 MVSep 官网核对。')
        account=check_account(token,progress)
        if str(account.get('premium_enabled'))=='1' and not allow_charges:raise CloudError('账户允许扣除 credits；请勾选费用确认后提交。')
        # Conservative free-tier ceiling; WAV16 may reach 100 MB before 10 minutes.
        premium=str(account.get('premium_enabled'))=='1' and float(account.get('premium_minutes') or 0)>0
        if length>(6000 if premium else 600):raise CloudError('超过当前方案时长上限（普通10分钟，Premium100分钟）；请在官网确认或自行分段，不自动切换模型。')
        audio=cache/'original.wav'
        progress('从所选原视频提取原始音轨（不使用旧分离成品）…')
        run([executable('ffmpeg'),'-v','error','-y','-ss',str(start),'-i',str(source),'-t',str(length),'-map','0:a:0','-vn','-c:a','pcm_s16le',str(audio)],cancel)
        if audio.stat().st_size>(1000 if premium else 100)*1000000:raise CloudError('提取音轨超过当前上传大小上限；未上传。')
        state['submission_started']=True;save()
        response=submit(audio,token,cancel,progress)
        if not response.get('success'):
            state.pop('submission_started',None);save();raise CloudError(message(response).replace(token,'[Token]'))
        state['hash']=response['data']['hash'];save()
    while True:
        if cancel.is_set():raise Cancelled('已停止本地等待；云端任务可能继续。重试会恢复原任务，不重复提交。')
        r=request_json('separation/get',{'hash':state['hash']});status=r.get('status');data=r.get('data') or {}
        if not r.get('success') or status in ('failed','not_found'):raise CloudError(message(r).replace(token,'[Token]')+'；保留任务记录，重试不重新计费提交。')
        if status=='done':break
        if status not in ('waiting','processing','distributing','merging'):raise CloudError('未知云端状态：'+str(status))
        text={'waiting':'排队','processing':'正在分离','distributing':'正在分发分段','merging':'正在合并'}[status]
        if status=='waiting':text+=f"；队列位置 {data.get('current_order','未知')} / {data.get('queue_count','未知')}"
        progress(text+'（云端未提供完成百分比）')
        cancel.wait(5)
    algorithm=data.get('algorithm')
    valid=(isinstance(algorithm,dict) and str(algorithm.get('render_id'))=='56') or (isinstance(algorithm,str) and algorithm=='MVSep DnR v3 (speech, music, effects)')
    if not valid:raise CloudError('返回模型与 DnR v3 不符；已停止。')
    url=music_file(data.get('files'));music=cache/'music.wav';temp=cache/'music.download'
    progress('下载 Music 音乐轨；不使用 Speech / Sfx…')
    try:
        with urllib.request.build_opener(Redirect()).open(url,timeout=60) as r,temp.open('wb') as f:
            while True:
                if cancel.is_set():raise Cancelled('下载已停止，重试恢复现有任务。')
                b=r.read(256*1024)
                if not b:break
                f.write(b)
        temp.replace(music)
    except Cancelled:raise
    except Exception:raise CloudError('Music 下载失败，重试将继续原任务。') from None
    md=float(probe(music,cancel)['format']['duration'])
    if abs(md-length)>.12:raise CloudError(f'Music 时长 {md:.3f} 秒与原片段 {length:.3f} 秒不一致；不加速、不截断讲话，已停止。')
    # Write a unique output. Original pictures are stream-copied for full videos.
    stem=source.stem+('_MVSep_20秒试听' if seconds else '_MVSep_仅保留背景音乐')
    out=folder/(stem+'.mp4');i=2
    while out.exists():out=folder/(stem+f'_{i}.mp4');i+=1
    partial=out.with_name(out.stem+'.partial.mp4')
    try:
        args=[executable('ffmpeg'),'-v','error','-y']
        if seconds:args+=['-ss',str(start)]
        args+=['-i',str(source),'-i',str(music),'-map','0:v:0','-map','1:a:0']
        args+=['-c:v','libx264','-preset','fast','-crf','18'] if seconds else ['-c:v','copy']
        args+=['-af',f'apad,atrim=duration={length}','-c:a','aac','-b:a','256k','-t',str(length),'-movflags','+faststart',str(partial)]
        progress('替换音轨并校验时长；完整视频画面直接复制…');run(args,cancel)
        result=probe(partial,cancel)
        if abs(float(result['format']['duration'])-length)>.15:raise CloudError('输出时长校验失败。')
        if not seconds and video_digest(source,cancel)!=video_digest(partial,cancel):raise CloudError('画面流一致性校验失败；不交付此结果。')
        run([executable('ffmpeg'),'-v','error','-i',str(partial),'-f','null','-'],cancel)
        partial.replace(out)
    finally:
        if partial.exists():partial.unlink()
    state['output']=str(out);save();out.with_suffix('.mvsep.json').write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf8')
    progress('已生成：'+str(out));return out

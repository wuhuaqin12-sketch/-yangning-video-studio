"""Real yue SRT alignment smoke using a short CC BY 4.0 SpiCE excerpt."""
import json,os,sys,tempfile,urllib.request
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'program'))
from alignment_runtime import prepare
from media import executable,parse_srt,run
from multilingual import align
from threading import Event

DOI='https://doi.org/10.5683/SP2/MJOXP3'
DATAFILE='https://dataverse.scholarsportal.info/api/access/datafile/165798'
TRANSCRIPT='新年快樂 恭喜發財 身體 健康 快高長大。'

def main():
    runner=Path(os.environ.get('RUNNER_TEMP',tempfile.gettempdir()))
    root=runner/'YangNingFormalAcceptance';root.mkdir(parents=True,exist_ok=True)
    data_root=Path(os.environ.get('YANGNING_DATA_ROOT',root/'cantonese-alignment-runtime'))
    os.environ['YANGNING_DATA_ROOT']=str(data_root)
    status=lambda message:print(message,flush=True)
    prepare(status)
request=urllib.request.Request(DATAFILE,headers={'Range':'bytes=0-6500000','User-Agent':'YangNingVideoStudio-CI/0.14.2'})
    with urllib.request.urlopen(request,timeout=90) as response:
        if response.status!=206 or not (response.headers.get('Content-Range','').startswith('bytes 0-')):
            raise RuntimeError('SpiCE 音频未返回所需的范围数据，停止真实粤语定位验收。')
        raw=response.read()
    if len(raw)<5_000_000:raise RuntimeError('SpiCE 粤语测试音频下载不完整。')
    source=root/'spice_cantonese_excerpt_source.wav';source.write_bytes(raw)
    audio=root/'spice_cantonese_excerpt.wav'
    subprocess_args=[executable('ffmpeg'),'-nostdin','-v','error','-y','-ss','29.36','-t','6.20','-i',str(source),'-c:a','pcm_s16le',str(audio)]
    run(subprocess_args,Event())
    srt=root/'spice_cantonese_reference.srt'
    srt.write_text('1\n00:00:00,100 --> 00:00:01,000\n'+TRANSCRIPT+'\n',encoding='utf-8-sig')
    cues=parse_srt(srt)
    align_folder=root/'yue-alignment';align_folder.mkdir(exist_ok=True)
    aligned=align(cues,audio,align_folder,Event(),status,'yue',6.20)
    words=json.loads((align_folder/'words.json').read_text(encoding='utf8'))
    if words.get('language')!='yue' or len(aligned)!=1 or aligned[0][3]!=TRANSCRIPT:
        raise AssertionError('粤语真实音频定位没有保留 yue 元数据或完整 SRT 文本。')
    if not 0<=aligned[0][1]<aligned[0][2]<=6.23:
        raise AssertionError('粤语真实音频定位时间超出音频片段。')
    result={'passed':True,'language':'yue','backend_language':'zh','dataset':'SpiCE Corpus','dataset_doi':DOI,
            'audio_seconds':6.2,'reference_srt':srt.name,'aligned_start':aligned[0][1],
            'aligned_end':aligned[0][2],'model':words.get('model'),'source_commit':os.environ.get('GITHUB_SHA','')}
    (root/'cantonese-alignment.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print('REAL_CANTONESE_SRT_ALIGNMENT_PASS',json.dumps(result,ensure_ascii=False),flush=True)

if __name__=='__main__':main()

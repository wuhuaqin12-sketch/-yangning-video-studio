"""Private stdin/stdout worker; keeps one model loaded, never opens a network port."""
import json
from pathlib import Path
import shutil
import sys
import traceback


def main():
    from huggingface_hub import snapshot_download
    from voxcpm_kaggle_worker import MODEL_ID,run
    if sys.argv[1]=="--prepare":
        import torch,voxcpm
        snapshot_download(MODEL_ID,cache_dir=sys.argv[2])
        print("LOCAL_ENVIRONMENT_READY",flush=True);return
    context={"cache_dir":sys.argv[1]}
    try:
        for line in sys.stdin:
            try:
                message=json.loads(line)
                if message.get("shutdown"): break
                request=json.loads(Path(message["request"]).read_text(encoding="utf-8"))
                import torch
                wanted=request.get("local_device","auto")
                device="cuda" if wanted=="auto" and torch.cuda.is_available() else ("cpu" if wanted=="auto" else wanted)
                if wanted=="cuda" and not torch.cuda.is_available(): raise ValueError("本机CUDA不可用，请检查显卡驱动或明确选择CPU。")
                if context.get("model") is not None and context["device"]!=device:
                    raise ValueError("设备已改变，请先释放本机模型后重试。")
                context["device"]=device
                run(request,local_context=context)
                result={"status":"done","device":device}
            except Exception as exc:
                traceback.print_exc()
                result={"status":"error","error":str(exc)}
            print("YANGNING_LOCAL="+json.dumps(result,ensure_ascii=False),flush=True)
    finally:
        if context.get("runtime"): shutil.rmtree(context["runtime"],ignore_errors=True)


if __name__=="__main__": main()

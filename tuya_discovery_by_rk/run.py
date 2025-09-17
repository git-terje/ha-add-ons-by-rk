import os, json, logging, subprocess
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%%Y-%%m-%%dT%%H:%%M:%%SZ")

def git_clone_or_pull(url, target="/data/repo"):
    if not url: return
    try:
        if not os.path.exists(target):
            logging.info(f"Cloning {url}")
            subprocess.run(["git","clone","--depth","1",url,target], check=True)
        else:
            subprocess.run(["git","-C",target,"pull","--ff-only"], check=True)
    except Exception as e:
        logging.error(f"git error: {e}")

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
def startup():
    try:
        with open("/data/options.json","r",encoding="utf-8") as f:
            opts = json.load(f)
        git_clone_or_pull(opts.get("git_repo",""))
    except Exception:
        pass
    logging.info("Tuya Discovery started")

@app.get("/health")
def health():
    return {"status":"ok"}

@app.get("/discover")
def discover():
    # Placeholder result; real discovery would require tinytuya broadcasts
    return {"devices":[{"id":"dummy","ip":"192.168.1.2","type":"unknown"}]}

if __name__ == "__main__":
    uvicorn.run("run:app", host="0.0.0.0", port=8097)

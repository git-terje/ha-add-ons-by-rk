import os, time, json, logging, subprocess
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%dT%H:%M:%SZ")

def git_clone_or_pull(url, target="/data/repo"):
    if not url: return
    try:
        if not os.path.exists(target):
            logging.info(f"Cloning {url} to {target}")
            subprocess.run(["git","clone","--depth","1",url,target], check=True)
        else:
            logging.info("Pulling latest changes")
            subprocess.run(["git","-C",target,"pull","--ff-only"], check=True)
    except Exception as e:
        logging.error(f"git error: {e}")

opts = {}
try:
    with open("/data/options.json","r",encoding="utf-8") as f:
        opts = json.load(f)
    git_clone_or_pull(opts.get("git_repo",""))
except Exception:
    pass

logging.info("Service started")
while True:
    logging.info("heartbeat")
    time.sleep(300)
